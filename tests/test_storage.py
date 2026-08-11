import json
from pathlib import Path

from wiki_updater.config import Settings
from wiki_updater.storage import Storage


def test_current_snapshot_path_falls_back_across_host_and_container_mounts(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, min_free_gb=0)
    settings.ensure_directories()
    snapshot = tmp_path / "snapshots" / "snapshot-1"
    snapshot.mkdir(parents=True)
    (tmp_path / "current.json").write_text(
        json.dumps({"snapshot_id": "snapshot-1", "path": "/host/path/not-visible/in-container"}),
        encoding="utf-8",
    )

    assert Storage(settings).current() == {
        "snapshot_id": "snapshot-1",
        "path": str(snapshot),
    }


def test_usage_does_not_count_hard_links_twice(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, min_free_gb=0)
    settings.ensure_directories()
    storage = Storage(settings)
    _digest, blob, _created = storage.put_blob(b"x" * 8192, ".bin")
    linked = tmp_path / "snapshots" / "one" / "content" / "asset.bin"
    storage.link_blob(blob, linked)

    before = storage.usage_bytes()
    linked_again = tmp_path / "snapshots" / "two" / "content" / "asset.bin"
    storage.link_blob(blob, linked_again)

    assert storage.usage_bytes() == before


def test_storage_purges_only_selected_regenerable_data(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, min_free_gb=0)
    settings.ensure_directories()
    storage = Storage(settings)
    current = tmp_path / "snapshots" / "current"
    old = tmp_path / "snapshots" / "old"
    current.mkdir(parents=True)
    old.mkdir(parents=True)
    (tmp_path / "current.json").write_text(
        json.dumps({"snapshot_id": "current", "path": str(current)}),
        encoding="utf-8",
    )
    (tmp_path / "builds" / "package.zip").write_bytes(b"build")
    (tmp_path / "work" / "abandoned").mkdir()

    storage.purge_work()
    storage.purge_builds()
    deleted = storage.keep_current_snapshot_only()

    assert not any((tmp_path / "work").iterdir())
    assert not any((tmp_path / "builds").iterdir())
    assert current.is_dir()
    assert not old.exists()
    assert deleted == 1
