import json
from pathlib import Path

from wiki_updater.candidates import create_candidate
from wiki_updater.config import Settings
from wiki_updater.database import Database, utcnow
from wiki_updater.jobs import finish
from wiki_updater.recovery import failed_validation, recover_failed_run, recoverable_failure
from wiki_updater.storage import Storage


FAILURE = (
    "Offline validation failed: {'pages': 2, 'expected_pages': 2, 'broken_links': 0, "
    "'missing_assets': 0, 'remote_resources': 0, 'asset_download_errors': 3}"
)


def test_asset_only_validation_failure_is_recoverable() -> None:
    run = {"status": "failed", "profile": "full", "error": FAILURE}
    assert failed_validation(FAILURE) == {
        "pages": 2,
        "expected_pages": 2,
        "broken_links": 0,
        "missing_assets": 0,
        "remote_resources": 0,
        "asset_download_errors": 3,
    }
    assert recoverable_failure(run)
    assert not recoverable_failure({**run, "error": FAILURE.replace("'broken_links': 0", "'broken_links': 1")})


def test_recover_failed_run_from_retained_blobs(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "updater.sqlite3",
        min_free_gb=0,
        storage_limit_gb=1,
        snapshot_retention=3,
        enabled_languages=("en",),
    )
    settings.ensure_directories()
    storage = Storage(settings)
    db = Database(settings)

    _asset_digest, asset_blob, _ = storage.put_blob(b"image", ".png")
    pages = []
    for page_id, title in ((1, "Home"), (2, "Villagers")):
        source = (
            f"<html><body><h1>{title}</h1>"
            f"<img src='../../assets/{asset_blob.parent.name}/{asset_blob.name}'></body></html>"
        ).encode()
        digest, _blob, _ = storage.put_blob(source, ".html")
        pages.append({
            "id": page_id,
            "title": title,
            "url": f"en/pages/{page_id}.html",
            "revision": page_id,
            "digest": digest,
            "text": title,
            "home": page_id == 1,
        })

    source_snapshot = tmp_path / "snapshots" / "sample-source"
    (source_snapshot / "content" / "search").mkdir(parents=True)
    (source_snapshot / "content" / "search" / "en.json").write_text(json.dumps(pages), encoding="utf-8")
    (tmp_path / "current.json").write_text(
        json.dumps({"snapshot_id": "sample-source", "path": str(source_snapshot)}),
        encoding="utf-8",
    )
    source_run_id = db.execute(
        "INSERT INTO runs(kind,profile,status,requested_by,created_at,started_at,finished_at,error) "
        "VALUES(?,?,?,?,?,?,?,?)",
        ("manual_sync", "full", "failed", "pytest", utcnow(), utcnow(), utcnow(), FAILURE),
    )
    db.execute(
        "INSERT INTO run_languages(run_id,language,status,pages_total,pages_written) VALUES(?,?,?,?,?)",
        (source_run_id, "en", "completed", 2, 2),
    )
    recovery_run_id = db.execute(
        "INSERT INTO runs(kind,profile,status,requested_by,created_at,started_at) VALUES(?,?,?,?,?,?)",
        ("recovery", f"recover-{source_run_id}", "running", "pytest", utcnow(), utcnow()),
    )

    snapshot_id, manifest = recover_failed_run(settings, db, recovery_run_id, source_run_id)

    recovered = tmp_path / "snapshots" / snapshot_id
    assert (recovered / "content" / "en" / "pages" / "1.html").is_file()
    assert (recovered / "content" / "en" / "pages" / "2.html").is_file()
    assert (recovered / "content" / "assets" / asset_blob.parent.name / asset_blob.name).is_file()
    assert manifest["validation"]["broken_links"] == 0
    assert manifest["validation"]["missing_assets"] == 0
    assert manifest["validation"]["asset_download_errors"] == 3
    assert manifest["warnings"][0]["code"] == "asset_download_errors"

    finish(
        db,
        recovery_run_id,
        "completed_with_warnings",
        snapshot_id=snapshot_id,
        summary=manifest,
    )
    candidate = create_candidate(settings, db, "v1.3.9", "pytest")
    assert candidate["status"] == "ready_with_warnings"
