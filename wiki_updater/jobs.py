from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from .database import Database, utcnow


TERMINAL_STATES = {
    "published", "rejected", "failed", "cancelled", "ready_for_review",
    "ready_with_warnings", "completed_with_warnings",
}


class RunCancelled(Exception):
    pass


def enqueue(db: Database, kind: str, profile: str, actor: str) -> int:
    with db.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        build = connection.execute(
            "SELECT id FROM build_jobs WHERE status IN ('queued','building') LIMIT 1"
        ).fetchone()
        if build:
            connection.execute("ROLLBACK")
            raise RuntimeError(f"Build {build['id']} is already queued or running.")
        active = connection.execute(
            "SELECT id FROM runs WHERE status IN ('queued','running','paused') LIMIT 1"
        ).fetchone()
        if active:
            connection.execute("ROLLBACK")
            raise RuntimeError(f"Run {active['id']} is already queued or running.")
        cursor = connection.execute(
            "INSERT INTO runs(kind,profile,status,requested_by,created_at) VALUES(?,?,?,?,?)",
            (kind, profile, "queued", actor, utcnow()),
        )
        run_id = int(cursor.lastrowid)
        connection.execute("COMMIT")
    db.event(run_id, f"Queued {kind} job with profile {profile}.")
    db.audit(actor, "run.enqueue", str(run_id), kind=kind, profile=profile)
    return run_id


def claim_next(db: Database) -> dict[str, Any] | None:
    with db.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute(
            "SELECT id FROM build_jobs WHERE status='building' LIMIT 1"
        ).fetchone():
            connection.execute("COMMIT")
            return None
        row = connection.execute("SELECT * FROM runs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not row:
            connection.execute("COMMIT")
            return None
        changed = connection.execute(
            "UPDATE runs SET status='running',started_at=? WHERE id=? AND status='queued'",
            (utcnow(), row["id"]),
        ).rowcount
        connection.execute("COMMIT")
        return dict(row) if changed else None


def reconcile_interrupted_runs(db: Database) -> None:
    """Close jobs whose in-memory worker disappeared before a restart."""
    for row in db.all("SELECT id,cancel_requested FROM runs WHERE status IN ('running','paused')"):
        run_id = int(row["id"])
        if row["cancel_requested"]:
            finish(db, run_id, "cancelled")
            db.audit("worker", "run.cancel.recovered", str(run_id))
        else:
            finish(db, run_id, "failed", error="Worker restarted before this run finished.")
            db.audit("worker", "run.interrupted", str(run_id))


def finish(db: Database, run_id: int, status: str, *, snapshot_id: str | None = None,
           error: str | None = None, summary: dict[str, Any] | None = None) -> None:
    db.execute(
        "UPDATE runs SET status=?,finished_at=?,snapshot_id=?,error=?,summary_json=?,"
        "cancel_requested=0,pause_requested=0 WHERE id=?",
        (status, utcnow(), snapshot_id, error, json.dumps(summary or {}, ensure_ascii=False), run_id),
    )
    db.event(run_id, f"Run finished with status {status}.", "error" if status == "failed" else "info")


def request_cancel(db: Database, run_id: int, actor: str) -> None:
    row = db.one("SELECT status FROM runs WHERE id=?", (run_id,))
    if not row:
        raise KeyError(run_id)
    if row["status"] == "queued":
        finish(db, run_id, "cancelled")
    elif row["status"] in {"running", "paused"}:
        db.execute("UPDATE runs SET cancel_requested=1,pause_requested=0 WHERE id=?", (run_id,))
        db.event(run_id, "Cancellation requested.", "warning")
    db.audit(actor, "run.cancel", str(run_id))


def cancellation_requested(db: Database, run_id: int) -> bool:
    row = db.one("SELECT cancel_requested FROM runs WHERE id=?", (run_id,))
    return bool(row and row["cancel_requested"])


def request_pause(db: Database, run_id: int, actor: str) -> None:
    row = db.one("SELECT status,pause_requested,cancel_requested FROM runs WHERE id=?", (run_id,))
    if not row:
        raise KeyError(run_id)
    if row["cancel_requested"]:
        raise RuntimeError("Cancellation has already been requested.")
    if row["status"] != "running":
        raise RuntimeError("Only a running synchronization can be paused.")
    if not row["pause_requested"]:
        db.execute("UPDATE runs SET pause_requested=1 WHERE id=?", (run_id,))
        db.event(run_id, "Pause requested; finishing in-flight work.", "warning")
        db.audit(actor, "run.pause", str(run_id))


def request_resume(db: Database, run_id: int, actor: str) -> None:
    row = db.one("SELECT status,pause_requested,cancel_requested FROM runs WHERE id=?", (run_id,))
    if not row:
        raise KeyError(run_id)
    if row["cancel_requested"]:
        raise RuntimeError("A cancelling synchronization cannot be resumed.")
    if row["status"] not in {"running", "paused"} or not row["pause_requested"]:
        raise RuntimeError("This synchronization is not paused.")
    db.execute(
        "UPDATE runs SET status='running',pause_requested=0 WHERE id=?",
        (run_id,),
    )
    db.event(run_id, "Synchronization resumed.")
    db.audit(actor, "run.resume", str(run_id))


async def control_checkpoint(db: Database, run_id: int) -> None:
    """Pause only between safe units of crawler work and honour cancellation."""
    pause_announced = False
    while True:
        row = db.one(
            "SELECT status,cancel_requested,pause_requested FROM runs WHERE id=?",
            (run_id,),
        )
        if not row or row["cancel_requested"]:
            raise asyncio.CancelledError
        if not row["pause_requested"]:
            return
        if row["status"] != "paused":
            db.execute(
                "UPDATE runs SET status='paused' WHERE id=? AND pause_requested=1",
                (run_id,),
            )
        if not pause_announced:
            db.event(run_id, "Synchronization paused at a safe checkpoint.", "warning")
            pause_announced = True
        await asyncio.sleep(0.5)


def control_checkpoint_sync(db: Database, run_id: int) -> None:
    """Synchronous counterpart for validation and local recovery loops."""
    pause_announced = False
    while True:
        row = db.one(
            "SELECT status,cancel_requested,pause_requested FROM runs WHERE id=?",
            (run_id,),
        )
        if not row or row["cancel_requested"]:
            raise RunCancelled
        if not row["pause_requested"]:
            return
        if row["status"] != "paused":
            db.execute(
                "UPDATE runs SET status='paused' WHERE id=? AND pause_requested=1",
                (run_id,),
            )
        if not pause_announced:
            db.event(run_id, "Synchronization paused at a safe checkpoint.", "warning")
            pause_announced = True
        time.sleep(0.5)
