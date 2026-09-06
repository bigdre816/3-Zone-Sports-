"""SQLite storage for the control plane.

WAL mode is enabled so the HTTP process and the separate WebSocket process can
read concurrently while a single writer commits. All JSON columns store text;
callers use the helpers here to (de)serialise.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL,               -- viewer | operator | admin
    account_state TEXT NOT NULL,               -- active | suspended
    subscription  TEXT NOT NULL,               -- active | inactive
    zones         TEXT NOT NULL DEFAULT '[]',  -- JSON list; ["*"] means all
    packages      TEXT NOT NULL DEFAULT '[]',  -- JSON list; ["*"] means all
    destinations  TEXT NOT NULL DEFAULT '[]'   -- JSON list; ["*"] means all
);

CREATE TABLE IF NOT EXISTS events (
    event_id         TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    zone             TEXT NOT NULL,
    category         TEXT NOT NULL DEFAULT 'general',
    status           TEXT NOT NULL,            -- lifecycle state
    scheduled_start  REAL NOT NULL,
    production_mode  TEXT NOT NULL DEFAULT 'single_camera',
    active_source    TEXT NOT NULL DEFAULT 'primary',   -- primary | backup
    primary_last_seen REAL,
    backup_last_seen  REAL,
    scoreboard       TEXT NOT NULL DEFAULT '{}',
    replay_available INTEGER NOT NULL DEFAULT 0,
    created_at       REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS rights (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id             TEXT NOT NULL,
    version              INTEGER NOT NULL,
    territory            TEXT NOT NULL,
    destination          TEXT NOT NULL,
    package              TEXT NOT NULL,
    live_start           REAL,
    live_end             REAL,
    replay_start         REAL,
    replay_end           REAL,
    authority            TEXT NOT NULL,
    source_reference     TEXT NOT NULL,
    active               INTEGER NOT NULL DEFAULT 1,
    revoked              INTEGER NOT NULL DEFAULT 0,
    revocation_reason    TEXT,
    archive_retention_days INTEGER NOT NULL DEFAULT 365,
    created_at           REAL NOT NULL,
    UNIQUE(event_id, version)
);

CREATE TABLE IF NOT EXISTS audit (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    actor     TEXT NOT NULL,
    action    TEXT NOT NULL,
    event_id  TEXT,
    detail    TEXT NOT NULL DEFAULT '{}'
);

-- Source-side delivery outbox. Three-Zone records locally first; a trusted
-- adapter may later submit this canonical source event to Treasure Network.
CREATE TABLE IF NOT EXISTS audit_verification_outbox (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id    INTEGER NOT NULL,
    event_json  TEXT NOT NULL,
    created_at  REAL NOT NULL,
    delivered_at REAL
);

CREATE TABLE IF NOT EXISTS socket_outbox (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id   TEXT NOT NULL,
    type       TEXT NOT NULL,
    payload    TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    delivered  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS socket_metrics (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    connections INTEGER NOT NULL DEFAULT 0,
    per_event   TEXT NOT NULL DEFAULT '{}',
    updated_at  REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_rights_event ON rights(event_id, version);
CREATE INDEX IF NOT EXISTS idx_outbox_undelivered ON socket_outbox(delivered, id);
CREATE INDEX IF NOT EXISTS idx_audit_verify_pending ON audit_verification_outbox(delivered_at, id);
"""


class Database:
    """Thin thread-safe wrapper around a single SQLite connection."""

    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            parent = os.path.dirname(os.path.abspath(path))
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA busy_timeout=5000;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self.init_schema()

    def init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.execute(
                "INSERT OR IGNORE INTO socket_metrics(id, connections, per_event, updated_at)"
                " VALUES (1, 0, '{}', 0)"
            )
            self._conn.commit()

    # --- primitives -------------------------------------------------------
    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: tuple = ()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur.lastrowid

    def executemany(self, sql: str, seq) -> None:
        with self._lock:
            self._conn.executemany(sql, seq)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def dumps(value) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def loads(text: str | None, default=None):
    if not text:
        return default
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default
