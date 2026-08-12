from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .config import get_settings
from .database import Database
from .snapshot_import import import_snapshot


def bootstrap_snapshot() -> None:
    settings = get_settings()
    if (settings.data_dir / "current.json").exists():
        print("[production] Existing /data/current.json found; snapshot bootstrap skipped.", flush=True)
        return
    seed_dir = Path(os.getenv("SNAPSHOT_SEED_DIR", "/opt/wiki-seed"))
    archives = sorted(seed_dir.glob("*.tar.zst"))
    if len(archives) != 1:
        raise RuntimeError("Production requires exactly one approved snapshot seed when /data is empty.")
    print("[production] Empty persistent data detected; importing approved snapshot seed.", flush=True)
    import_snapshot(settings, Database(settings), archives[0], "production-bootstrap")


def run_production() -> None:
    bootstrap_snapshot()
    settings = get_settings()
    print(
        f"[production] Starting dashboard on 0.0.0.0:8080 "
        f"(worker_enabled={settings.worker_enabled}, builder_enabled={settings.builder_enabled}).",
        flush=True,
    )
    commands = [["uvicorn", "wiki_updater.web:app", "--host", "0.0.0.0", "--port", "8080"]]
    if settings.worker_enabled:
        commands.append(["wiki-updater", "worker"])
    children = [subprocess.Popen(command) for command in commands]
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        for child in children:
            if child.poll() is None:
                child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while True:
            exited = next((child for child in children if child.poll() is not None), None)
            if exited:
                stop(signal.SIGTERM, None)
                return_code = int(exited.returncode or 0)
                if return_code:
                    raise SystemExit(return_code)
                return
            time.sleep(0.5)
    finally:
        stop(signal.SIGTERM, None)
        for child in children:
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
