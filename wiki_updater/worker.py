from __future__ import annotations

import asyncio
import signal
from contextlib import suppress

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import Settings
from .crawler import synchronize
from .database import Database
from .jobs import claim_next, enqueue, finish
from .recovery import RecoveryCancelled, recover_failed_run


def schedule_job(db: Database, kind: str, profile: str) -> None:
    if not db.setting("enabled", True):
        return
    try:
        enqueue(db, kind, profile, "scheduler")
    except RuntimeError:
        pass


def backup_database(db: Database, settings: Settings) -> None:
    destination = db.backup(settings.data_dir / "backups")
    db.audit("scheduler", "database.backup", str(destination))


async def process(db: Database, settings: Settings, run: dict[str, object]) -> None:
    run_id = int(run["id"])
    try:
        enabled_languages = tuple(db.setting("enabled_languages", list(settings.enabled_languages)))
        page_concurrency = int(db.setting("page_concurrency", settings.page_concurrency))
        run_settings = settings.model_copy(update={
            "enabled_languages": enabled_languages,
            "page_concurrency": page_concurrency,
        })
        if run["kind"] == "recovery":
            source_run_id = int(str(run["profile"]).removeprefix("recover-"))
            snapshot_id, manifest = await asyncio.to_thread(
                recover_failed_run, run_settings, db, run_id, source_run_id
            )
        else:
            snapshot_id, manifest = await synchronize(run_settings, db, run_id, str(run["profile"]))
        status = "completed_with_warnings" if manifest.get("warnings") else "completed"
        finish(db, run_id, status, snapshot_id=snapshot_id, summary=manifest)
    except asyncio.CancelledError:
        finish(db, run_id, "cancelled")
    except RecoveryCancelled:
        finish(db, run_id, "cancelled")
    except Exception as exc:
        finish(db, run_id, "failed", error=str(exc))


async def run_worker(settings: Settings, db: Database) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signal_name, stop.set)

    scheduler = BackgroundScheduler(timezone=settings.timezone)
    scheduler.add_job(
        schedule_job,
        CronTrigger(day_of_week="sun", hour=3, minute=0, timezone=settings.timezone),
        args=(db, "weekly_sync", "incremental"),
        id="weekly-sync",
        replace_existing=True,
    )
    scheduler.add_job(
        backup_database,
        CronTrigger(hour=2, minute=30, timezone=settings.timezone),
        args=(db, settings),
        id="sqlite-backup",
        replace_existing=True,
    )
    scheduler.add_job(
        schedule_job,
        CronTrigger(day=1, hour=3, minute=0, timezone=settings.timezone),
        args=(db, "monthly_reconcile", "full"),
        id="monthly-reconcile",
        replace_existing=True,
    )
    if settings.enabled and db.setting("enabled", True):
        scheduler.start()
    try:
        while not stop.is_set():
            run = claim_next(db)
            if run:
                await process(db, settings, run)
            else:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1)
                except TimeoutError:
                    pass
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
