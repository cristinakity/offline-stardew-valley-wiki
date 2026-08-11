from __future__ import annotations

import ast
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .crawler import OFFLINE_CSS, atomic_write_text, validate_content
from .database import Database
from .storage import Storage, sha256_bytes


CONTENT_ASSET_RE = re.compile(
    rb"(?:\.\./)+assets/([0-9a-f]{2})/([0-9a-f]{64}(?:\.[A-Za-z0-9]{1,16})?)"
)
CSS_ASSET_RE = re.compile(
    rb"\.\./([0-9a-f]{2})/([0-9a-f]{64}(?:\.[A-Za-z0-9]{1,16})?)"
)


def failed_validation(error: str | None) -> dict[str, int] | None:
    if not error or "Offline validation failed:" not in error:
        return None
    try:
        parsed = ast.literal_eval(error[error.index("{"):])
    except (ValueError, SyntaxError):
        return None
    if not isinstance(parsed, dict):
        return None
    try:
        return {str(key): int(value) for key, value in parsed.items()}
    except (TypeError, ValueError):
        return None


def recoverable_failure(run: dict[str, Any]) -> bool:
    validation = failed_validation(run.get("error"))
    return bool(
        run.get("status") == "failed"
        and run.get("profile") in {"full", "incremental"}
        and validation
        and validation.get("pages") == validation.get("expected_pages")
        and validation.get("asset_download_errors", 0) > 0
        and not any(validation.get(key, 0) for key in ("broken_links", "missing_assets", "remote_resources"))
    )


def _snapshot_roots(settings: Settings, storage: Storage) -> list[Path]:
    roots: list[Path] = []
    current = storage.current()
    if current:
        configured = Path(str(current.get("path", "")))
        fallback = settings.data_dir / "snapshots" / str(current.get("snapshot_id", ""))
        roots.extend(path for path in (configured, fallback) if path.is_dir())
    roots.extend(sorted((settings.data_dir / "snapshots").glob("*"), reverse=True))
    return list(dict.fromkeys(path.resolve() for path in roots if path.is_dir()))


def _find_complete_indexes(
    settings: Settings,
    storage: Storage,
    language_rows: list[dict[str, Any]],
) -> tuple[Path, dict[str, list[dict[str, Any]]]]:
    for snapshot_root in _snapshot_roots(settings, storage):
        indexes: dict[str, list[dict[str, Any]]] = {}
        for row in language_rows:
            language = str(row["language"])
            index_path = snapshot_root / "content" / "search" / f"{language}.json"
            if not index_path.is_file():
                break
            documents = json.loads(index_path.read_text(encoding="utf-8"))
            if len(documents) != int(row["pages_total"]):
                break
            if any(not item.get("digest") for item in documents):
                break
            indexes[language] = documents
        if len(indexes) == len(language_rows):
            return snapshot_root, indexes
    raise RuntimeError("No retained search indexes contain every page from the failed run.")


def _link_referenced_assets(storage: Storage, content_root: Path, page_paths: list[Path]) -> int:
    pending: list[tuple[str, str]] = []
    for page in page_paths:
        pending.extend(
            (prefix.decode("ascii"), name.decode("ascii"))
            for prefix, name in CONTENT_ASSET_RE.findall(page.read_bytes())
        )
    linked: set[tuple[str, str]] = set()
    while pending:
        prefix, name = pending.pop()
        key = (prefix, name)
        if key in linked:
            continue
        if not name.startswith(prefix) or not re.fullmatch(r"[0-9a-f]{64}(?:\.[A-Za-z0-9]{1,16})?", name):
            raise RuntimeError(f"Unsafe content-addressed asset reference: {prefix}/{name}")
        blob = storage.blobs / prefix / name
        if not blob.is_file():
            raise RuntimeError(f"Required retained asset blob is missing: {prefix}/{name}")
        storage.link_blob(blob, content_root / "assets" / prefix / name)
        linked.add(key)
        if blob.suffix.lower() == ".css":
            pending.extend(
                (child_prefix.decode("ascii"), child_name.decode("ascii"))
                for child_prefix, child_name in CSS_ASSET_RE.findall(blob.read_bytes())
            )
    return len(linked)


def recover_failed_run(settings: Settings, db: Database, recovery_run_id: int, source_run_id: int) -> tuple[str, dict[str, Any]]:
    source_run = db.one("SELECT * FROM runs WHERE id=?", (source_run_id,))
    if not source_run:
        raise KeyError(source_run_id)
    if not recoverable_failure(source_run):
        raise RuntimeError("This run is not recoverable: only optional asset downloads may have failed.")
    language_rows = db.all(
        "SELECT * FROM run_languages WHERE run_id=? ORDER BY language",
        (source_run_id,),
    )
    if not language_rows or any(row["status"] != "completed" for row in language_rows):
        raise RuntimeError("The failed run did not complete every language.")

    storage = Storage(settings)
    storage.ensure_capacity()
    source_snapshot, indexes = _find_complete_indexes(settings, storage, language_rows)
    work = settings.data_dir / "work" / f"recovery-{recovery_run_id}"
    shutil.rmtree(work, ignore_errors=True)
    content_root = work / "content"
    content_root.mkdir(parents=True)
    atomic_write_text(content_root / "offline.css", OFFLINE_CSS + "\n")
    db.event(
        recovery_run_id,
        f"Recovering failed run #{source_run_id} from retained content-addressed blobs.",
        source_run_id=source_run_id,
        index_snapshot=str(source_snapshot),
    )

    page_paths: list[Path] = []
    pages_by_language: dict[str, list[dict[str, Any]]] = {}
    try:
        for row in language_rows:
            language = str(row["language"])
            documents = indexes[language]
            db.execute(
                "INSERT OR REPLACE INTO run_languages("
                "run_id,language,status,pages_total,pages_written,assets_written,bytes_written,revision_start,revision_end"
                ") VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    recovery_run_id, language, "running", len(documents), 0, 0, 0,
                    row.get("revision_start"), row.get("revision_end"),
                ),
            )
            for document in documents:
                digest = str(document["digest"])
                blob = storage.blobs / digest[:2] / f"{digest}.html"
                if not blob.is_file():
                    raise RuntimeError(f"Page blob {digest} for {language}/{document['id']} is missing.")
                destination = content_root / language / "pages" / f"{int(document['id'])}.html"
                storage.link_blob(blob, destination)
                page_paths.append(destination)
            atomic_write_text(
                content_root / "search" / f"{language}.json",
                json.dumps(documents, ensure_ascii=False, separators=(",", ":")) + "\n",
            )
            pages_by_language[language] = [{"pageid": int(item["id"])} for item in documents]
            db.execute(
                "UPDATE run_languages SET status='completed',pages_written=? WHERE run_id=? AND language=?",
                (len(documents), recovery_run_id, language),
            )
            db.event(recovery_run_id, f"{language}: restored {len(documents)} page blobs.", language=language)

        asset_count = _link_referenced_assets(storage, content_root, page_paths)
        db.event(recovery_run_id, f"Restored {asset_count} referenced asset blobs.", assets=asset_count)
        validation = validate_content(content_root, pages_by_language)
        source_validation = failed_validation(source_run.get("error")) or {}
        validation["asset_download_errors"] = source_validation.get("asset_download_errors", 0)
        if any(validation[key] for key in ("broken_links", "missing_assets", "remote_resources")):
            raise RuntimeError(f"Recovered content validation failed: {validation}")

        generated = datetime.now(timezone.utc)
        language_stats = {
            str(row["language"]): {
                "pages": int(row["pages_total"]),
                "pages_updated": int(row["pages_written"]),
                "assets_added": int(row["assets_written"]),
                "bytes_written": int(row["bytes_written"]),
                "revision_start": row.get("revision_start"),
                "revision_end": row.get("revision_end"),
            }
            for row in language_rows
        }
        manifest: dict[str, Any] = {
            "schema": 1,
            "generated_at": generated.isoformat(),
            "profile": "full",
            "recovered_from_run": source_run_id,
            "page_concurrency": None,
            "http_concurrency": 0,
            "languages": language_stats,
            "validation": validation,
            "warnings": [{
                "code": "asset_download_errors",
                "count": validation["asset_download_errors"],
                "message": (
                    f"{validation['asset_download_errors']} optional assets were unavailable in source run "
                    f"#{source_run_id}; all retained offline content passed structural validation."
                ),
            }],
            "asset_failures": [],
        }
        digest = sha256_bytes(json.dumps(manifest, sort_keys=True).encode())
        snapshot_id = f"{generated:%Y%m%dT%H%M%SZ}-{digest[:12]}"
        manifest["snapshot_id"] = snapshot_id
        manifest["digest"] = digest
        storage.promote(snapshot_id, content_root, manifest)
        db.event(
            recovery_run_id,
            "Recovered snapshot passed offline validation with asset warnings.",
            level="warning",
            snapshot_id=snapshot_id,
            **validation,
        )
        db.audit("worker", "run.recover", str(source_run_id), recovery_run_id=recovery_run_id, snapshot_id=snapshot_id)
        return snapshot_id, manifest
    finally:
        shutil.rmtree(work, ignore_errors=True)
