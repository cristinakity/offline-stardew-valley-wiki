from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import shutil
from contextlib import suppress
from pathlib import Path
from typing import Any

from .config import LANGUAGES, Settings
from .database import Database, utcnow
from .storage import Storage


EDITIONS = ("multilingual", *LANGUAGES)
PLATFORMS = ("linux",)
PROGRESS_RE = re.compile(r"^BUILD_PROGRESS\s+(\S+)\s+(\d+)\s+(\d+)$", re.MULTILINE)
BUILDING_RE = re.compile(r"^Building Linux edition:\s+(\S+)\s*$", re.MULTILINE)
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _plain_build_output(value: str) -> str:
    """Remove terminal control sequences emitted by Electron Forge."""
    return ANSI_ESCAPE_RE.sub("", value).replace("\r", "")


def _live_build_progress(db: Database, job_id: int) -> tuple[int, int, str | None] | None:
    """Recover live progress from the worker log without modifying the job."""
    log_path = db.path.parent / "logs" / f"build-{job_id}.log"
    if not log_path.is_file():
        return None
    with log_path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - 512 * 1024))
        output = _plain_build_output(handle.read().decode("utf-8", errors="replace"))
    completed = list(PROGRESS_RE.finditer(output))
    building = list(BUILDING_RE.finditer(output))
    if not completed and not building:
        return None
    current = int(completed[-1].group(2)) if completed else 0
    total = int(completed[-1].group(3)) if completed else 0
    edition = building[-1].group(1) if building else None
    return current, total, edition


def _candidate_archive(item: dict[str, Any]) -> Path:
    directory = Path(str(item["directory"])).resolve()
    archives = sorted(directory.glob("wiki-content-*.tar.zst"))
    if len(archives) != 1 or not archives[0].is_file() or archives[0].parent != directory:
        raise RuntimeError("Candidate must contain exactly one wiki-content-*.tar.zst archive.")
    return archives[0]


def _pin_candidate_archive(db: Database, candidate_id: int, archive: Path) -> Path:
    sources = db.path.parent / "build-sources"
    sources.mkdir(parents=True, exist_ok=True)
    pinned = sources / f"candidate-{candidate_id}-{archive.name}"
    if pinned.exists():
        if not pinned.is_file() or pinned.is_symlink():
            raise RuntimeError("Pinned candidate build source is unsafe.")
        return pinned.resolve()
    try:
        os.link(archive, pinned)
    except OSError:
        shutil.copy2(archive, pinned)
    return pinned.resolve()


def enqueue_build(
    db: Database,
    candidate_id: int,
    edition: str,
    platform: str,
    actor: str,
) -> int:
    edition = edition.casefold()
    platform = platform.casefold()
    if edition not in {"all", *EDITIONS}:
        raise ValueError(f"Unsupported edition: {edition}")
    if platform not in PLATFORMS:
        raise ValueError(f"Unsupported local platform: {platform}")
    item = db.one("SELECT * FROM candidates WHERE id=?", (candidate_id,))
    if not item:
        raise KeyError(candidate_id)
    archive = _pin_candidate_archive(db, candidate_id, _candidate_archive(item))
    total = len(EDITIONS) if edition == "all" else 1
    job_id = db.execute(
        "INSERT INTO build_jobs("
        "candidate_id,version,snapshot_id,edition,platform,status,requested_by,created_at,"
        "source_archive,progress_total"
        ") VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            candidate_id,
            item["version"],
            item["snapshot_id"],
            edition,
            platform,
            "queued",
            actor,
            utcnow(),
            str(archive),
            total,
        ),
    )
    db.build_event(job_id, f"Queued {platform} build for edition {edition}.")
    db.audit(
        actor,
        "build.enqueue",
        str(job_id),
        candidate_id=candidate_id,
        version=item["version"],
        snapshot_id=item["snapshot_id"],
        edition=edition,
        platform=platform,
    )
    return job_id


def enqueue_rebuild(db: Database, source_job_id: int, actor: str) -> int:
    source = db.one("SELECT * FROM build_jobs WHERE id=?", (source_job_id,))
    if not source:
        raise KeyError(source_job_id)
    if source["status"] not in {"completed", "failed"}:
        raise RuntimeError("Only a finished build can be rebuilt.")
    archive = Path(str(source["source_archive"]))
    if not archive.is_file():
        raise RuntimeError("The original candidate archive is no longer available.")
    total = len(EDITIONS) if source["edition"] == "all" else 1
    job_id = db.execute(
        "INSERT INTO build_jobs("
        "candidate_id,version,snapshot_id,edition,platform,status,requested_by,created_at,"
        "source_archive,progress_total"
        ") VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            source["candidate_id"], source["version"], source["snapshot_id"],
            source["edition"], source["platform"], "queued", actor, utcnow(),
            str(archive), total,
        ),
    )
    db.build_event(job_id, f"Queued as an exact rebuild of build #{source_job_id}.")
    db.audit(actor, "build.rebuild", str(job_id), source_build_job_id=source_job_id)
    return job_id


def build_job(db: Database, job_id: int, *, event_limit: int = 200) -> dict[str, Any] | None:
    item = db.one("SELECT * FROM build_jobs WHERE id=?", (job_id,))
    if not item:
        return None
    if item["status"] == "building":
        live = _live_build_progress(db, job_id)
        if live:
            current, total, edition = live
            item["progress_current"] = max(int(item["progress_current"]), current)
            if total:
                item["progress_total"] = total
            item["current_edition"] = edition
    output = Path(str(item["output_directory"])) if item.get("output_directory") else None
    item["assets"] = [
        {"name": path.name, "size": path.stat().st_size}
        for path in sorted(output.iterdir())
        if output and output.is_dir() and path.is_file() and not path.is_symlink()
        and (path.suffix.casefold() in {".zip", ".deb", ".rpm"} or path.name == "SHA256SUMS")
    ] if output and output.is_dir() else []
    events = db.all(
        "SELECT id,created_at,level,message FROM build_events WHERE build_job_id=? "
        "ORDER BY id DESC LIMIT ?",
        (job_id, min(max(event_limit, 1), 1000)),
    )
    item["events"] = list(reversed(events))
    return item


def list_build_jobs(db: Database, limit: int = 50) -> list[dict[str, Any]]:
    rows = db.all("SELECT id FROM build_jobs ORDER BY id DESC LIMIT ?", (min(max(limit, 1), 200),))
    return [item for row in rows if (item := build_job(db, int(row["id"]))) is not None]


def claim_next_build(db: Database) -> dict[str, Any] | None:
    with db.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM build_jobs WHERE status='queued' ORDER BY id LIMIT 1"
        ).fetchone()
        if not row:
            connection.execute("COMMIT")
            return None
        output = str(db.path.parent / "builds" / f"job-{int(row['id']):06d}")
        changed = connection.execute(
            "UPDATE build_jobs SET status='building',started_at=?,output_directory=? "
            "WHERE id=? AND status='queued'",
            (utcnow(), output, row["id"]),
        ).rowcount
        connection.execute("COMMIT")
        return {**dict(row), "output_directory": output} if changed else None


def finish_build(db: Database, job_id: int, status: str, error: str | None = None) -> None:
    if status not in {"completed", "failed"}:
        raise ValueError(status)
    db.execute(
        "UPDATE build_jobs SET status=?,finished_at=?,error=? WHERE id=?",
        (status, utcnow(), error, job_id),
    )
    db.build_event(job_id, f"Build finished with status {status}.", "error" if error else "info")


def reconcile_interrupted_builds(db: Database) -> None:
    for row in db.all("SELECT id FROM build_jobs WHERE status='building'"):
        finish_build(db, int(row["id"]), "failed", "Builder worker restarted before this build finished.")


async def execute_build(settings: Settings, db: Database, job: dict[str, Any]) -> None:
    job_id = int(job["id"])
    archive = Path(str(job["source_archive"])).resolve()
    sources_root = (settings.data_dir / "build-sources").resolve()
    if archive.parent != sources_root or archive.is_symlink() or not archive.is_file():
        raise RuntimeError("The candidate source archive is no longer available.")
    output = Path(str(job["output_directory"])).resolve()
    builds_root = (settings.data_dir / "builds").resolve()
    if output.parent != builds_root:
        raise RuntimeError("Unsafe build output directory.")
    output.mkdir(parents=True, exist_ok=False)
    Storage(settings).ensure_capacity(estimated_extra=archive.stat().st_size)
    log_path = settings.data_dir / "logs" / f"build-{job_id}.log"
    script = Path(os.getenv("BUILD_SCRIPT", "/workspace/scripts/build-linux.sh"))
    environment = {
        **os.environ,
        "DATA_DIR": str(settings.data_dir),
        "CANDIDATE_ARCHIVE": str(archive),
        "CANDIDATE_VERSION": str(job["version"]),
        "BUILD_JOB_ID": str(job_id),
        "BUILD_DESTINATION": str(output),
        "WIKI_EDITION": str(job["edition"]),
    }
    db.build_event(job_id, f"Using immutable candidate archive {archive.name}.")
    process = await asyncio.create_subprocess_exec(
        "bash",
        str(script),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=environment,
        cwd=str(script.parent.parent),
    )
    assert process.stdout is not None
    with log_path.open("a", encoding="utf-8") as log:
        async for payload in process.stdout:
            line = payload.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            log.write(line + "\n")
            log.flush()
            plain_line = _plain_build_output(line)
            progress = PROGRESS_RE.fullmatch(plain_line)
            if progress:
                edition, current, total = progress.groups()
                db.execute(
                    "UPDATE build_jobs SET progress_current=?,progress_total=? WHERE id=?",
                    (int(current), int(total), job_id),
                )
                db.build_event(job_id, f"Completed edition {edition} ({current}/{total}).")
            elif plain_line.startswith(("Building Linux edition:", "Preparing candidate archive:")):
                db.build_event(job_id, plain_line)
    return_code = await process.wait()
    if return_code:
        raise RuntimeError(f"Linux builder exited with status {return_code}. See {log_path.name}.")


async def run_build_worker(settings: Settings, db: Database) -> None:
    reconcile_interrupted_builds(db)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signal_name, stop.set)
    while not stop.is_set():
        job = claim_next_build(db)
        if not job:
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                pass
            continue
        job_id = int(job["id"])
        try:
            await execute_build(settings, db, job)
            db.execute(
                "UPDATE build_jobs SET progress_current=progress_total WHERE id=?",
                (job_id,),
            )
            finish_build(db, job_id, "completed")
            db.audit("builder-worker", "build.completed", str(job_id))
        except Exception as exc:
            finish_build(db, job_id, "failed", str(exc))
            db.audit("builder-worker", "build.failed", str(job_id), error=str(exc))
