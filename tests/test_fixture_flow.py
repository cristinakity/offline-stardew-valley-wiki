import asyncio
import json
from pathlib import Path

from wiki_updater.candidates import create_candidate, delete_candidate
from wiki_updater.config import Settings
from wiki_updater.crawler import synchronize
from wiki_updater.database import Database, utcnow
from wiki_updater.jobs import finish
from wiki_updater.snapshot_import import import_snapshot


def test_fixture_sync_and_candidate(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "test.sqlite3",
        min_free_gb=0,
        storage_limit_gb=1,
        enabled_languages=("en", "es", "zh"),
    )
    settings.ensure_directories()
    db = Database(settings)
    run_id = db.execute(
        "INSERT INTO runs(kind,profile,status,requested_by,created_at,started_at) VALUES(?,?,?,?,?,?)",
        ("test", "fixture", "running", "pytest", utcnow(), utcnow()),
    )
    snapshot_id, manifest = asyncio.run(synchronize(settings, db, run_id, "fixture"))
    finish(db, run_id, "completed", snapshot_id=snapshot_id, summary=manifest)
    assert manifest["validation"]["broken_links"] == 0
    assert manifest["validation"]["missing_assets"] == 0
    assert manifest["validation"]["remote_resources"] == 0
    assert manifest["validation"]["pages"] == 6
    assert manifest["page_concurrency"] == 2
    assert manifest["http_concurrency"] == 2
    current = json.loads((tmp_path / "current.json").read_text())
    assert current["snapshot_id"] == snapshot_id
    es_pages = tmp_path / "snapshots" / snapshot_id / "content" / "es" / "pages"
    rendered = "\n".join(path.read_text(encoding="utf-8") for path in es_pages.glob("*.html"))
    assert "data-src=" not in rendered
    assert "srcset=" in rendered
    assert "https://" not in rendered
    assert "Content-Security-Policy" in rendered
    search_documents = json.loads(
        (tmp_path / "snapshots" / snapshot_id / "content" / "search" / "es.json").read_text()
    )
    assert all(document["text"] for document in search_documents)

    candidate = create_candidate(settings, db, "v1.3.0", "pytest", run_id=run_id)
    assert candidate["status"] == "ready_for_review"
    assert candidate["run_id"] == run_id
    assert candidate["manifest"]["profile"] == "fixture"
    assert {asset["name"] for asset in candidate["assets"]} >= {
        "content-lock.json", "validation-report.json", "SHA256SUMS"
    }
    archive = next(Path(candidate["directory"]).glob("wiki-content-*.tar.zst"))
    imported_root = tmp_path / "imported"
    imported_settings = Settings(
        data_dir=imported_root,
        database_path=imported_root / "updater.sqlite3",
        min_free_gb=0,
        storage_limit_gb=1,
        enabled_languages=("en", "es", "zh"),
    )
    imported_db = Database(imported_settings)
    imported = import_snapshot(imported_settings, imported_db, archive, "pytest")
    assert imported["snapshot_id"] == snapshot_id
    assert imported["validation"]["pages"] == 6
    assert json.loads((imported_root / "current.json").read_text())["snapshot_id"] == snapshot_id
    candidate_directory = Path(candidate["directory"])
    delete_candidate(settings, db, candidate["id"], "pytest")
    assert not candidate_directory.exists()
    assert db.one("SELECT id FROM candidates WHERE id=?", (candidate["id"],)) is None
