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
        """Return allocated bytes once per inode, so hard links are not double-counted."""
        total = 0
        seen: set[tuple[int, int]] = set()
        for root, _dirs, files in os.walk(self.settings.data_dir):
            for name in files:
                path = Path(root) / name
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    continue
                inode = (stat.st_dev, stat.st_ino)
                if inode in seen:
                    continue
                seen.add(inode)
                total += stat.st_blocks * 512
        return total

    @staticmethod
    def directory_usage(path: Path) -> dict[str, int]:
        allocated = logical = files = 0
        seen: set[tuple[int, int]] = set()
        if not path.exists():
            return {"allocated_bytes": 0, "logical_bytes": 0, "files": 0}
        for root, _dirs, names in os.walk(path):
            for name in names:
                item = Path(root) / name
                try:
                    stat = item.stat()
                except FileNotFoundError:
                    continue
                inode = (stat.st_dev, stat.st_ino)
                if inode in seen:
                    continue
                seen.add(inode)
                allocated += stat.st_blocks * 512
                logical += stat.st_size
                files += 1
        return {"allocated_bytes": allocated, "logical_bytes": logical, "files": files}

    def usage_breakdown(self) -> dict[str, Any]:
        categories = ("blobs", "snapshots", "candidates", "builds", "work", "logs", "backups")
        return {
            "physical_bytes": self.usage_bytes(),
            "categories": {
                name: self.directory_usage(self.settings.data_dir / name)
                for name in categories
            },
        }

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
        if not path.exists():
            return None
        current = json.loads(path.read_text(encoding="utf-8"))
        configured = Path(str(current.get("path", "")))
        fallback = self.settings.data_dir / "snapshots" / str(current.get("snapshot_id", ""))
        if not configured.is_dir() and fallback.is_dir():
            current["path"] = str(fallback)
        return current

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

    def purge_work(self) -> None:
        work = self.settings.data_dir / "work"
        for item in work.iterdir():
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item)
            else:
                item.unlink(missing_ok=True)

    def purge_builds(self) -> None:
        builds = self.settings.data_dir / "builds"
        for item in builds.iterdir():
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item)
            else:
                item.unlink(missing_ok=True)

    def keep_current_snapshot_only(self) -> int:
        current = self.current()
        if not current:
            raise RuntimeError("There is no current snapshot to preserve.")
        current_id = str(current["snapshot_id"])
        deleted = 0
        for snapshot in (self.settings.data_dir / "snapshots").iterdir():
            if snapshot.is_dir() and not snapshot.is_symlink() and snapshot.name != current_id:
                shutil.rmtree(snapshot)
                deleted += 1
        self.prune_unreferenced_blobs()
        return deleted
