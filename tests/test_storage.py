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
