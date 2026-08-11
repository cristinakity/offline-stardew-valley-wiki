from __future__ import annotations

import argparse
import asyncio
import json

from .candidates import create_candidate
from .builds import run_build_worker
from .config import get_settings
from .crawler import synchronize
from .database import Database, utcnow
from .jobs import finish
from .recovery import RecoveryCancelled, recover_failed_run
from .snapshot_import import import_snapshot
from .worker import run_worker


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="wiki-updater")
    commands = root.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("sync", help="Run a synchronization in the foreground")
    sync.add_argument("--profile", choices=("fixture", "sample", "incremental", "full"), default="fixture")
    candidate = commands.add_parser("candidate", help="Create a local candidate from the current snapshot")
    candidate.add_argument("--version", default="v1.3.0")
    snapshot_import = commands.add_parser("snapshot-import", help="Import an approved snapshot archive")
    snapshot_import.add_argument("--archive", type=str, required=True)
    recover = commands.add_parser("recover", help="Recover a structurally valid failed run from retained blobs")
    recover.add_argument("--run-id", type=int, required=True)
    commands.add_parser("worker", help="Run scheduler and queued jobs")
    commands.add_parser("build-worker", help="Run queued candidate package builds")
    commands.add_parser("production", help="Run dashboard and worker in one production container")
    commands.add_parser("doctor", help="Print local configuration and storage information")
    return root


async def foreground_sync(profile: str) -> None:
    settings = get_settings()
    db = Database(settings)
    run_id = db.execute(
        "INSERT INTO runs(kind,profile,status,requested_by,created_at,started_at) VALUES(?,?,?,?,?,?)",
        ("manual_sync", profile, "running", "cli", utcnow(), utcnow()),
    )
    try:
        snapshot_id, manifest = await synchronize(settings, db, run_id, profile)
        status = "completed_with_warnings" if manifest.get("warnings") else "completed"
        finish(db, run_id, status, snapshot_id=snapshot_id, summary=manifest)
        print(json.dumps({"run_id": run_id, "snapshot_id": snapshot_id, "manifest": manifest}, indent=2))
    except asyncio.CancelledError:
        finish(db, run_id, "cancelled")
        print(json.dumps({"run_id": run_id, "status": "cancelled"}, indent=2))
    except Exception as exc:
        finish(db, run_id, "failed", error=str(exc))
        raise


def main() -> None:
    args = parser().parse_args()
    settings = get_settings()
    db = Database(settings)
    if args.command == "worker":
        asyncio.run(run_worker(settings, db))
    elif args.command == "build-worker":
        asyncio.run(run_build_worker(settings, db))
    elif args.command == "sync":
        asyncio.run(foreground_sync(args.profile))
    elif args.command == "candidate":
        print(json.dumps(create_candidate(settings, db, args.version, "cli"), indent=2))
    elif args.command == "snapshot-import":
        from pathlib import Path

        print(json.dumps(import_snapshot(settings, db, Path(args.archive), "cli"), indent=2))
    elif args.command == "recover":
        run_id = db.execute(
            "INSERT INTO runs(kind,profile,status,requested_by,created_at,started_at) VALUES(?,?,?,?,?,?)",
            ("recovery", f"recover-{args.run_id}", "running", "cli", utcnow(), utcnow()),
        )
        try:
            snapshot_id, manifest = recover_failed_run(settings, db, run_id, args.run_id)
            finish(db, run_id, "completed_with_warnings", snapshot_id=snapshot_id, summary=manifest)
            print(json.dumps({"run_id": run_id, "snapshot_id": snapshot_id, "manifest": manifest}, indent=2))
        except RecoveryCancelled:
            finish(db, run_id, "cancelled")
            print(json.dumps({"run_id": run_id, "status": "cancelled"}, indent=2))
        except Exception as exc:
            finish(db, run_id, "failed", error=str(exc))
            raise
    elif args.command == "production":
        from .production import run_production

        run_production()
    elif args.command == "doctor":
        from .storage import Storage

        storage = Storage(settings)
        print(json.dumps({
            "environment": settings.app_env,
            "data_dir": str(settings.data_dir),
            "database": str(settings.database_path),
            "languages": settings.enabled_languages,
            "storage_used_bytes": storage.usage_bytes(),
            "storage_limit_gb": settings.storage_limit_gb,
            "minimum_free_gb": settings.min_free_gb,
            "current": storage.current(),
        }, indent=2))


if __name__ == "__main__":
    main()
