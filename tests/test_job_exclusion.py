from pathlib import Path

import pytest

from wiki_updater.config import Settings
from wiki_updater.database import Database, utcnow
from wiki_updater.jobs import enqueue


def test_crawler_is_rejected_while_build_is_active(tmp_path: Path) -> None:
    db = Database(Settings(data_dir=tmp_path, min_free_gb=0))
    db.execute(
        "INSERT INTO build_jobs(candidate_id,version,snapshot_id,edition,platform,status,"
        "requested_by,created_at,source_archive,progress_total) VALUES(NULL,?,?,?,?,?,?,?,?,?)",
        ("v1.3.0", "snapshot", "en", "linux", "building", "pytest", utcnow(), "/tmp/source", 1),
    )
    with pytest.raises(RuntimeError, match="Build .* already queued or running"):
        enqueue(db, "manual_sync", "incremental", "pytest")
