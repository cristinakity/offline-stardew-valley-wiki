from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from .config import Settings
from .crawler import validate_content
from .database import Database, utcnow
from .jobs import finish
from .storage import Storage, sha256_bytes


def _archive_members(archive: Path) -> list[str]:
    completed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    members = [line.strip().removeprefix("./") for line in completed.stdout.splitlines() if line.strip()]
    for member in members:
        path = PurePosixPath(member)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError(f"Snapshot archive contains an unsafe path: {member}")
        if member != "manifest.json" and not member.startswith("content/"):
            raise RuntimeError(f"Snapshot archive contains an unexpected path: {member}")
    if "manifest.json" not in members or not any(member.startswith("content/") for member in members):
        raise RuntimeError("Snapshot archive must contain manifest.json and content/.")
    return members


def _verify_manifest(manifest: dict[str, Any]) -> None:
    expected = str(manifest.get("digest", ""))
    snapshot_id = str(manifest.get("snapshot_id", ""))
    digest_source = {key: value for key, value in manifest.items() if key not in {"digest", "snapshot_id"}}
    actual = sha256_bytes(json.dumps(digest_source, sort_keys=True).encode())
    if not expected or actual != expected:
        raise RuntimeError("Snapshot manifest digest does not match its contents.")
    if not snapshot_id.endswith(f"-{expected[:12]}"):
        raise RuntimeError("Snapshot ID does not match the manifest digest.")


def import_snapshot(settings: Settings, db: Database, archive: Path, actor: str) -> dict[str, Any]:
    archive = archive.resolve()
    if not archive.is_file():
        raise FileNotFoundError(archive)
    _archive_members(archive)
    storage = Storage(settings)
    storage.ensure_capacity(archive.stat().st_size * 3)
    work = settings.data_dir / "work" / f"import-{uuid.uuid4().hex}"
    work.mkdir(parents=True)
    run_id = db.execute(
        "INSERT INTO runs(kind,profile,status,requested_by,created_at,started_at) VALUES(?,?,?,?,?,?)",
        ("snapshot_import", "import", "running", actor, utcnow(), utcnow()),
    )
    db.event(run_id, "Extracting and validating an approved snapshot archive.", archive=archive.name)
    try:
        subprocess.run(
            [
                "tar", "--zstd", "--extract", "--file", str(archive), "--directory", str(work),
                "--no-same-owner", "--no-same-permissions",
            ],
            check=True,
        )
        if any(path.is_symlink() for path in work.rglob("*")):
            raise RuntimeError("Snapshot archive may not contain symbolic links.")
        manifest = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
        _verify_manifest(manifest)
        snapshot_id = str(manifest["snapshot_id"])
        search_root = work / "content" / "search"
        pages_by_language: dict[str, list[dict[str, Any]]] = {}
        for index_path in search_root.glob("*.json"):
            documents = json.loads(index_path.read_text(encoding="utf-8"))
            pages_by_language[index_path.stem] = [{"pageid": item["id"]} for item in documents]
        validation = validate_content(work / "content", pages_by_language)
        if any(validation[key] for key in ("broken_links", "missing_assets", "remote_resources")):
            raise RuntimeError(f"Imported snapshot validation failed: {validation}")
        if (settings.data_dir / "snapshots" / snapshot_id).exists():
            raise RuntimeError(f"Snapshot {snapshot_id} already exists.")
        storage.promote(snapshot_id, work / "content", manifest)
        finish(db, run_id, "completed", snapshot_id=snapshot_id, summary={"validation": validation})
        db.audit(actor, "snapshot.import", snapshot_id, archive=archive.name)
        return {"run_id": run_id, "snapshot_id": snapshot_id, "validation": validation}
    except Exception as exc:
        finish(db, run_id, "failed", error=str(exc))
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
