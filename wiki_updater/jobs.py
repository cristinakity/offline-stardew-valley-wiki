from __future__ import annotations

import json
from typing import Any

from .database import Database, utcnow


TERMINAL_STATES = {"published", "rejected", "failed", "cancelled", "ready_for_review"}


def enqueue(db: Database, kind: str, profile: str, actor: str) -> int:
    active = db.one("SELECT id FROM runs WHERE status IN ('queued','running') LIMIT 1")
    if active:
        raise RuntimeError(f"Run {active['id']} is already queued or running.")
    run_id = db.execute(
        "INSERT INTO runs(kind,profile,status,requested_by,created_at) VALUES(?,?,?,?,?)",
        (kind, profile, "queued", actor, utcnow()),
    )
    db.event(run_id, f"Queued {kind} job with profile {profile}.")
    db.audit(actor, "run.enqueue", str(run_id), kind=kind, profile=profile)
    return run_id


def claim_next(db: Database) -> dict[str, Any] | None:
    with db.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
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


def finish(db: Database, run_id: int, status: str, *, snapshot_id: str | None = None,
           error: str | None = None, summary: dict[str, Any] | None = None) -> None:
    db.execute(
        "UPDATE runs SET status=?,finished_at=?,snapshot_id=?,error=?,summary_json=? WHERE id=?",
        (status, utcnow(), snapshot_id, error, json.dumps(summary or {}, ensure_ascii=False), run_id),
    )
    db.event(run_id, f"Run finished with status {status}.", "error" if status == "failed" else "info")


def request_cancel(db: Database, run_id: int, actor: str) -> None:
    row = db.one("SELECT status FROM runs WHERE id=?", (run_id,))
    if not row:
        raise KeyError(run_id)
    if row["status"] == "queued":
        finish(db, run_id, "cancelled")
    elif row["status"] == "running":
        db.execute("UPDATE runs SET cancel_requested=1 WHERE id=?", (run_id,))
        db.event(run_id, "Cancellation requested.", "warning")
    db.audit(actor, "run.cancel", str(run_id))


def cancellation_requested(db: Database, run_id: int) -> bool:
    row = db.one("SELECT cancel_requested FROM runs WHERE id=?", (run_id,))
    return bool(row and row["cancel_requested"])

