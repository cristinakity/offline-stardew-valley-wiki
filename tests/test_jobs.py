from pathlib import Path

import pytest

from wiki_updater.config import Settings
from wiki_updater.database import Database
from wiki_updater.jobs import claim_next, enqueue, request_cancel


def database(tmp_path: Path) -> Database:
    settings = Settings(data_dir=tmp_path, min_free_gb=0)
    settings.ensure_directories()
    return Database(settings)


def test_only_one_run_can_be_active(tmp_path: Path) -> None:
    db = database(tmp_path)
    first = enqueue(db, "manual_sync", "fixture", "tester")
    assert first > 0
    with pytest.raises(RuntimeError, match="already"):
        enqueue(db, "manual_sync", "fixture", "tester")
    claimed = claim_next(db)
    assert claimed and claimed["id"] == first


def test_queued_run_can_be_cancelled(tmp_path: Path) -> None:
    db = database(tmp_path)
    run_id = enqueue(db, "manual_sync", "fixture", "tester")
    request_cancel(db, run_id, "tester")
    assert db.one("SELECT status FROM runs WHERE id=?", (run_id,))["status"] == "cancelled"


def test_sqlite_backup_is_readable(tmp_path: Path) -> None:
    db = database(tmp_path)
    enqueue(db, "manual_sync", "fixture", "tester")
    backup = db.backup(tmp_path / "backups")
    restored = Settings(data_dir=tmp_path / "restored", database_path=backup, min_free_gb=0)
    assert Database(restored).one("SELECT COUNT(*) AS count FROM runs")["count"] == 1
