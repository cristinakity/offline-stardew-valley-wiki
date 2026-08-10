from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .config import Settings


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class Storage:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.ensure_directories()

    @property
    def blobs(self) -> Path:
        return self.settings.data_dir / "blobs"

    def usage_bytes(self) -> int:
        total = 0
        for root, _dirs, files in os.walk(self.settings.data_dir):
            for name in files:
                path = Path(root) / name
                try:
                    total += path.stat().st_size
                except FileNotFoundError:
                    pass
        return total

    def ensure_capacity(self, estimated_extra: int = 0) -> None:
        usage = self.usage_bytes()
        limit = self.settings.storage_limit_gb * 1024**3
        free = shutil.disk_usage(self.settings.data_dir).free
        reserve = self.settings.min_free_gb * 1024**3
        if usage + estimated_extra > limit:
            raise RuntimeError(
                f"Storage budget exceeded: {usage / 1024**3:.2f} GiB used, "
                f"{self.settings.storage_limit_gb} GiB configured."
            )
        if free - estimated_extra < reserve:
            raise RuntimeError(
                f"Free-space reserve would be violated: {free / 1024**3:.2f} GiB free, "
                f"{self.settings.min_free_gb} GiB must remain."
            )

    def put_blob(self, payload: bytes, suffix: str = "") -> tuple[str, Path, bool]:
        digest = sha256_bytes(payload)
        suffix = suffix.lower()[:16] if suffix.startswith(".") else ""
        destination = self.blobs / digest[:2] / f"{digest}{suffix}"
        created = not destination.exists()
        if created:
            self.ensure_capacity(len(payload))
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.write_bytes(payload)
            temporary.replace(destination)
        return digest, destination, created

    @staticmethod
    def link_blob(blob: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.unlink(missing_ok=True)
        try:
            os.link(blob, destination)
        except OSError:
            shutil.copy2(blob, destination)

    def current(self) -> dict[str, Any] | None:
        path = self.settings.data_dir / "current.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def promote(self, snapshot_id: str, work_content: Path, manifest: dict[str, Any]) -> Path:
        destination = self.settings.data_dir / "snapshots" / snapshot_id
        if destination.exists():
            raise RuntimeError(f"Snapshot {snapshot_id} already exists.")
        destination.mkdir(parents=True)
        work_content.replace(destination / "content")
        (destination / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        current = self.settings.data_dir / "current.json"
        temporary = current.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"snapshot_id": snapshot_id, "path": str(destination)}, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(current)
        self.prune_snapshots()
        return destination

    def prune_snapshots(self) -> None:
        snapshots = sorted(
            (path for path in (self.settings.data_dir / "snapshots").iterdir() if path.is_dir()),
            key=lambda path: path.name,
            reverse=True,
        )
        for old in snapshots[self.settings.snapshot_retention :]:
            shutil.rmtree(old)
        self.prune_unreferenced_blobs()

    def prune_unreferenced_blobs(self) -> None:
        """Delete CAS objects no longer hard-linked by a retained snapshot or active worktree."""
        for blob in self.blobs.glob("*/*"):
            try:
                if blob.is_file() and blob.stat().st_nlink == 1:
                    blob.unlink()
            except FileNotFoundError:
                pass
        for prefix in self.blobs.iterdir():
            if prefix.is_dir():
                try:
                    prefix.rmdir()
                except OSError:
                    pass
