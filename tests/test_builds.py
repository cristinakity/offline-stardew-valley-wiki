from __future__ import annotations

from pathlib import Path

import pytest

from wiki_updater.builds import (
    EDITIONS,
    build_job,
    claim_next_build,
    enqueue_build,
    enqueue_rebuild,
    finish_build,
)
from wiki_updater.config import Settings
from wiki_updater.database import Database, utcnow


def build_database(tmp_path: Path) -> tuple[Settings, Database, int, Path]:
    settings = Settings(data_dir=tmp_path, min_free_gb=0)
    settings.ensure_directories()
    db = Database(settings)
    candidate_dir = tmp_path / "candidates" / "v1.4.0"
    candidate_dir.mkdir()
    archive = candidate_dir / "wiki-content-snapshot-abc.tar.zst"
    archive.write_bytes(b"immutable candidate")
    run_id = db.execute(
        "INSERT INTO runs(kind,profile,status,requested_by,created_at) VALUES(?,?,?,?,?)",
        ("manual_sync", "full", "completed", "pytest", utcnow()),
    )
    candidate_id = db.execute(
        "INSERT INTO candidates(run_id,version,status,snapshot_id,created_at,updated_at,directory) "
        "VALUES(?,?,?,?,?,?,?)",
        (
            run_id, "v1.4.0", "published", "snapshot-abc", utcnow(), utcnow(),
            str(candidate_dir),
        ),
    )
    return settings, db, candidate_id, archive


def test_build_job_is_pinned_to_candidate_archive(tmp_path: Path) -> None:
    _settings, db, candidate_id, archive = build_database(tmp_path)
    job_id = enqueue_build(db, candidate_id, "ja", "linux", "pytest")
    queued = build_job(db, job_id)
    assert queued
    assert Path(queued["source_archive"]).samefile(archive)
    assert Path(queued["source_archive"]).parent == tmp_path / "build-sources"
    assert queued["snapshot_id"] == "snapshot-abc"
    assert queued["version"] == "v1.4.0"
    assert queued["progress_total"] == 1

    claimed = claim_next_build(db)
    assert claimed and claimed["id"] == job_id
    assert Path(claimed["output_directory"]).name == f"job-{job_id:06d}"


def test_all_editions_and_exact_rebuild_get_separate_jobs(tmp_path: Path) -> None:
    _settings, db, candidate_id, archive = build_database(tmp_path)
    first = enqueue_build(db, candidate_id, "all", "linux", "pytest")
    claim_next_build(db)
    finish_build(db, first, "completed")
    rebuilt = enqueue_rebuild(db, first, "pytest")
    assert rebuilt != first
    item = build_job(db, rebuilt)
    assert item
    assert item["edition"] == "all"
    assert item["progress_total"] == len(EDITIONS)
    assert Path(item["source_archive"]).samefile(archive)
    assert item["status"] == "queued"


def test_build_rejects_unknown_edition_and_platform(tmp_path: Path) -> None:
    _settings, db, candidate_id, _archive = build_database(tmp_path)
    with pytest.raises(ValueError, match="Unsupported edition"):
        enqueue_build(db, candidate_id, "xx", "linux", "pytest")
    with pytest.raises(ValueError, match="Unsupported local platform"):
        enqueue_build(db, candidate_id, "en", "windows", "pytest")
