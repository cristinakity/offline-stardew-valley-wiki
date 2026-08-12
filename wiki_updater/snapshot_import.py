from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from .config import Settings
from .crawler import validate_content
from .database import Database, utcnow
from .jobs import finish
from .storage import Storage, sha256_bytes


def _log(message: str) -> None:
    print(f"[snapshot-import] {message}", flush=True)


def _elapsed(started: float) -> str:
    return f"{time.monotonic() - started:.1f}s"


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


def _quick_validate_content(
    content_root: Path,
    pages_by_language: dict[str, list[dict[str, Any]]],
    manifest: dict[str, Any],
) -> dict[str, int]:
    """Validate immutable snapshot structure without reparsing every HTML document."""
    expected_languages = manifest.get("languages", {})
    if set(pages_by_language) != set(expected_languages):
        raise RuntimeError("Snapshot languages do not match the signed manifest.")
    if not (content_root / "offline.css").is_file() or not (content_root / "translations.json").is_file():
        raise RuntimeError("Snapshot is missing required offline metadata.")

    page_count = 0
    sampled = 0
    for language, documents in sorted(pages_by_language.items()):
        expected = int(expected_languages[language]["pages"])
        if len(documents) != expected:
            raise RuntimeError(
                f"{language} search index contains {len(documents)} pages; manifest expects {expected}."
            )
        page_paths = [content_root / language / "pages" / f"{int(item['pageid'])}.html" for item in documents]
        missing = next((path for path in page_paths if not path.is_file()), None)
        if missing:
            raise RuntimeError(f"Indexed offline page is missing: {missing.relative_to(content_root)}")
        if page_paths:
            sample_indexes = sorted({0, len(page_paths) // 2, len(page_paths) - 1})
            for index in sample_indexes:
                sample = page_paths[index].read_text(encoding="utf-8")
                if not sample.strip() or "Content-Security-Policy" not in sample:
                    raise RuntimeError(
                        f"Sampled offline page is empty or lacks its CSP: {page_paths[index].relative_to(content_root)}"
                    )
                sampled += 1
        page_count += len(page_paths)

    signed_validation = manifest.get("validation", {})
    for key in ("broken_links", "missing_assets", "remote_resources"):
        if int(signed_validation.get(key, -1)) != 0:
            raise RuntimeError(f"Signed snapshot validation is not clean: {key}={signed_validation.get(key)}")
    return {
        "pages": page_count,
        "expected_pages": page_count,
        "broken_links": 0,
        "missing_assets": 0,
        "remote_resources": 0,
        "sampled_pages": sampled,
    }


def import_snapshot(settings: Settings, db: Database, archive: Path, actor: str) -> dict[str, Any]:
    started = time.monotonic()
    archive = archive.resolve()
    if not archive.is_file():
        raise FileNotFoundError(archive)
    archive_size = archive.stat().st_size
    _log(f"Starting approved snapshot import: {archive.name} ({archive_size / 1024**2:.1f} MiB).")
    _log("Phase 1/6: inspecting archive members and validating paths.")
    members = _archive_members(archive)
    _log(f"Archive inspection complete: {len(members):,} members ({_elapsed(started)} elapsed).")
    storage = Storage(settings)
    _log("Phase 2/6: checking storage budget and free-space reserve.")
    storage.ensure_capacity(archive_size * 3)
    work = settings.data_dir / "work" / f"import-{uuid.uuid4().hex}"
    work.mkdir(parents=True)
    run_id = db.execute(
        "INSERT INTO runs(kind,profile,status,requested_by,created_at,started_at) VALUES(?,?,?,?,?,?)",
        ("snapshot_import", "import", "running", actor, utcnow(), utcnow()),
    )
    db.event(run_id, "Extracting and validating an approved snapshot archive.", archive=archive.name)
    try:
        phase_started = time.monotonic()
        _log("Phase 3/6: extracting compressed snapshot. This can take several minutes.")
        subprocess.run(
            [
                "tar", "--zstd", "--extract", "--file", str(archive), "--directory", str(work),
                "--no-same-owner", "--no-same-permissions",
            ],
            check=True,
        )
        _log(f"Extraction complete ({_elapsed(phase_started)}). Checking extracted files and manifest.")
        if any(path.is_symlink() for path in work.rglob("*")):
            raise RuntimeError("Snapshot archive may not contain symbolic links.")
        manifest = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
        _verify_manifest(manifest)
        snapshot_id = str(manifest["snapshot_id"])
        _log(f"Manifest verified for snapshot {snapshot_id}.")
        _log("Phase 4/6: loading per-language search indexes.")
        search_root = work / "content" / "search"
        pages_by_language: dict[str, list[dict[str, Any]]] = {}
        for index_path in search_root.glob("*.json"):
            documents = json.loads(index_path.read_text(encoding="utf-8"))
            pages_by_language[index_path.stem] = [{"pageid": item["id"]} for item in documents]
            _log(f"Loaded {index_path.stem}: {len(documents):,} pages.")
        total_pages = sum(len(pages) for pages in pages_by_language.values())
        _log(
            f"Phase 5/6: validating {total_pages:,} offline pages in "
            f"{settings.bootstrap_validation} mode."
        )
        validation_started = time.monotonic()

        def validation_progress(processed: int, expected: int) -> None:
            if processed == 1 or processed % 500 == 0 or processed == expected:
                percent = (processed * 100 // expected) if expected else 100
                _log(
                    f"Validation progress: {processed:,}/{expected:,} pages ({percent}%, "
                    f"{_elapsed(validation_started)} elapsed)."
                )

        if settings.bootstrap_validation == "quick":
            validation = _quick_validate_content(work / "content", pages_by_language, manifest)
        else:
            validation = validate_content(work / "content", pages_by_language, progress=validation_progress)
        _log(f"Offline validation complete: {validation} ({_elapsed(validation_started)}).")
        if any(validation[key] for key in ("broken_links", "missing_assets", "remote_resources")):
            raise RuntimeError(f"Imported snapshot validation failed: {validation}")
        if (settings.data_dir / "snapshots" / snapshot_id).exists():
            raise RuntimeError(f"Snapshot {snapshot_id} already exists.")
        _log("Phase 6/6: promoting validated content and updating current.json.")
        storage.promote(snapshot_id, work / "content", manifest)
        finish(db, run_id, "completed", snapshot_id=snapshot_id, summary={"validation": validation})
        db.audit(actor, "snapshot.import", snapshot_id, archive=archive.name)
        _log(f"Snapshot import completed successfully in {_elapsed(started)}. Starting dashboard.")
        return {"run_id": run_id, "snapshot_id": snapshot_id, "validation": validation}
    except Exception as exc:
        finish(db, run_id, "failed", error=str(exc))
        _log(f"Snapshot import failed after {_elapsed(started)}: {type(exc).__name__}: {exc}")
        raise
    finally:
        _log("Cleaning temporary import workspace.")
        shutil.rmtree(work, ignore_errors=True)
