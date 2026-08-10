from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import Settings


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    profile TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    snapshot_id TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS run_languages (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    language TEXT NOT NULL,
    status TEXT NOT NULL,
    pages_total INTEGER NOT NULL DEFAULT 0,
    pages_written INTEGER NOT NULL DEFAULT 0,
    assets_written INTEGER NOT NULL DEFAULT 0,
    bytes_written INTEGER NOT NULL DEFAULT 0,
    revision_start TEXT,
    revision_end TEXT,
    error TEXT,
    PRIMARY KEY (run_id, language)
);

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    version TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    directory TEXT NOT NULL,
    manifest_json TEXT NOT NULL DEFAULT '{}',
    error TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, settings: Settings):
        assert settings.database_path is not None
        self.path = Path(settings.database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(SCHEMA)

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> int:
        with self.connection() as connection:
            cursor = connection.execute(sql, parameters)
            return int(cursor.lastrowid or 0)

    def one(self, sql: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(sql, parameters).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connection() as connection:
            return [dict(row) for row in connection.execute(sql, parameters).fetchall()]

    def event(self, run_id: int, message: str, level: str = "info", **detail: Any) -> None:
        self.execute(
            "INSERT INTO run_events(run_id,created_at,level,message,detail_json) VALUES(?,?,?,?,?)",
            (run_id, utcnow(), level, message, json.dumps(detail, ensure_ascii=False, sort_keys=True)),
        )

    def audit(self, actor: str, action: str, target: str | None = None, **detail: Any) -> None:
        self.execute(
            "INSERT INTO audit_events(created_at,actor,action,target,detail_json) VALUES(?,?,?,?,?)",
            (utcnow(), actor, action, target, json.dumps(detail, ensure_ascii=False, sort_keys=True)),
        )

    def setting(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value_json FROM settings WHERE key=?", (key,))
        return json.loads(row["value_json"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings(key,value_json,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), utcnow()),
        )

    def backup(self, backup_dir: Path, keep: int = 7) -> Path:
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = backup_dir / f"updater-{stamp}.sqlite3"
        with self.connect() as source, sqlite3.connect(destination) as target:
            source.backup(target)
        backups = sorted(backup_dir.glob("updater-*.sqlite3"), reverse=True)
        for expired in backups[keep:]:
            expired.unlink()
        return destination
