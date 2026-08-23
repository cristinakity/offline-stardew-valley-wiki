from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import Settings
from .database import Database, utcnow
from .storage import Storage


VERSION_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_candidate(
    settings: Settings,
    db: Database,
    version: str,
    actor: str,
    run_id: int | None = None,
) -> dict[str, Any]:
    if not VERSION_RE.fullmatch(version):
        raise ValueError("Version must look like v2.0.0 or 2.0.0.")
    version = version if version.startswith("v") else f"v{version}"
    storage = Storage(settings)
    if run_id is not None:
        run = db.one("SELECT * FROM runs WHERE id=?", (run_id,))
        if not run:
            raise RuntimeError(f"Run #{run_id} does not exist.")
        if run["status"] not in {"completed", "completed_with_warnings"} or not run.get("snapshot_id"):
            raise RuntimeError(f"Run #{run_id} does not have a completed snapshot.")
        snapshot_id = run["snapshot_id"]
        snapshot_dir = settings.data_dir / "snapshots" / snapshot_id
    else:
        current = storage.current()
        if not current:
            raise RuntimeError("A successful snapshot is required before creating a candidate.")
        snapshot_id = current["snapshot_id"]
        snapshot_dir = Path(current["path"])
        run = db.one("SELECT * FROM runs WHERE snapshot_id=? ORDER BY id DESC LIMIT 1", (snapshot_id,))
        if not run:
            raise RuntimeError("Snapshot does not have a matching run record.")
    if not snapshot_dir.is_dir() or not (snapshot_dir / "manifest.json").is_file():
        raise RuntimeError(f"The retained snapshot for run #{run['id']} is no longer available.")
    manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))

    candidate_dir = settings.data_dir / "candidates" / version
    if candidate_dir.exists():
        raise RuntimeError(f"Candidate {version} already exists.")
    candidate_dir.mkdir(parents=True)
    lock = {
        "schema": 1,
        "version": version,
        "snapshot_id": snapshot_id,
        "snapshot_digest": manifest["digest"],
        "generated_at": manifest["generated_at"],
        "languages": manifest["languages"],
        "profile": run["profile"],
        "run_id": run["id"],
    }
    (candidate_dir / "content-lock.json").write_text(
        json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (candidate_dir / "validation-report.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    archive = candidate_dir / f"wiki-content-{snapshot_id}.tar.zst"
    storage.ensure_capacity(estimated_extra=max(storage.usage_bytes() // 2, 50 * 1024**2))
    subprocess.run(
        ["tar", "--zstd", "-cf", str(archive), "-C", str(snapshot_dir), "content", "manifest.json"],
        check=True,
    )
    checksums = []
    for path in sorted(candidate_dir.iterdir()):
        if path.name != "SHA256SUMS" and path.is_file():
            checksums.append(f"{file_sha256(path)}  {path.name}")
    (candidate_dir / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="utf-8")

    now = utcnow()
    candidate_status = "ready_with_warnings" if manifest.get("warnings") else "ready_for_review"
    candidate_id = db.execute(
        "INSERT INTO candidates(run_id,version,status,snapshot_id,created_at,updated_at,directory,manifest_json) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (
            run["id"], version, candidate_status, snapshot_id, now, now, str(candidate_dir),
            json.dumps(lock, ensure_ascii=False),
        ),
    )
    db.audit(actor, "candidate.create", str(candidate_id), version=version, snapshot_id=snapshot_id)
    return candidate(db, candidate_id) or {}


def candidate(db: Database, candidate_id: int) -> dict[str, Any] | None:
    item = db.one("SELECT * FROM candidates WHERE id=?", (candidate_id,))
    if not item:
        return None
    directory = Path(item["directory"])
    item["assets"] = [
        {"name": path.name, "size": path.stat().st_size, "sha256": file_sha256(path)}
        for path in sorted(directory.iterdir()) if path.is_file()
    ] if directory.exists() else []
    item["manifest"] = json.loads(item.pop("manifest_json"))
    return item


def set_candidate_status(settings: Settings, db: Database, candidate_id: int, status: str, actor: str) -> dict[str, Any]:
    if status not in {"published", "rejected", "ready_for_review", "ready_with_warnings"}:
        raise ValueError(status)
    item = candidate(db, candidate_id)
    if not item:
        raise KeyError(candidate_id)
    if settings.app_env != "local" and status == "published":
        raise RuntimeError("Remote publication is intentionally disabled until the GitHub approval phase is configured.")
    db.execute("UPDATE candidates SET status=?,updated_at=? WHERE id=?", (status, utcnow(), candidate_id))
    db.audit(actor, f"candidate.{status}", str(candidate_id), version=item["version"])
    return candidate(db, candidate_id) or {}


def delete_candidate(settings: Settings, db: Database, candidate_id: int, actor: str) -> None:
    item = candidate(db, candidate_id)
    if not item:
        raise KeyError(candidate_id)
    candidates_root = (settings.data_dir / "candidates").resolve()
    directory = Path(item["directory"]).resolve()
    if directory.parent != candidates_root:
        raise RuntimeError("Candidate directory is outside the configured candidates directory.")
    if directory.exists():
        shutil.rmtree(directory)
    db.execute("DELETE FROM candidates WHERE id=?", (candidate_id,))
    db.audit(actor, "candidate.delete", str(candidate_id), version=item["version"])
