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
        return
    seed_dir = Path(os.getenv("SNAPSHOT_SEED_DIR", "/opt/wiki-seed"))
    archives = sorted(seed_dir.glob("*.tar.zst"))
    if len(archives) != 1:
        raise RuntimeError("Production requires exactly one approved snapshot seed when /data is empty.")
    import_snapshot(settings, Database(settings), archives[0], "production-bootstrap")


def run_production() -> None:
    bootstrap_snapshot()
    commands = [
        ["uvicorn", "wiki_updater.web:app", "--host", "0.0.0.0", "--port", "8080"],
        ["wiki-updater", "worker"],
    ]
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
