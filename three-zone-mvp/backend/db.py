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
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL,               -- viewer | operator | admin
    account_state TEXT NOT NULL,               -- active | suspended
    subscription  TEXT NOT NULL,               -- active | inactive
    zones         TEXT NOT NULL DEFAULT '[]',  -- JSON list; ["*"] means all
    packages      TEXT NOT NULL DEFAULT '[]',  -- JSON list; ["*"] means all
    destinations  TEXT NOT NULL DEFAULT '[]',  -- JSON list; ["*"] means all
    password_hash TEXT NOT NULL DEFAULT '',
    properties    TEXT NOT NULL DEFAULT '[]'
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
    created_at       REAL NOT NULL,
    media_provider   TEXT NOT NULL DEFAULT 'demo',
    provider_input_id TEXT,
    provider_video_id TEXT,
    provider_replay_video_id TEXT,
    provider_state   TEXT NOT NULL DEFAULT '',
    provider_last_webhook_at REAL,
    provider_last_error TEXT,
    replay_pending   INTEGER NOT NULL DEFAULT 0,
    property_id      TEXT
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

-- Members-portal V1 domains. These tables supplement the original control
-- plane tables; original events and rights remain the PDP source of truth.
CREATE TABLE IF NOT EXISTS member_sessions (
    session_id TEXT PRIMARY KEY, member_id TEXT NOT NULL, verification_id TEXT,
    entitlement_version INTEGER NOT NULL, device_binding TEXT NOT NULL,
    status TEXT NOT NULL, issued_at REAL NOT NULL, expires_at REAL NOT NULL,
    revoked_at REAL
);
CREATE TABLE IF NOT EXISTS member_verifications (
    verification_id TEXT PRIMARY KEY, member_id TEXT NOT NULL, status TEXT NOT NULL,
    verification_type TEXT NOT NULL, verified_at REAL, expires_at REAL,
    evidence_hash TEXT, verifier TEXT NOT NULL, receipt_id TEXT, simulated INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS schools (
    school_id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, territory TEXT NOT NULL DEFAULT 'midwest'
);
CREATE TABLE IF NOT EXISTS teams (
    team_id TEXT PRIMARY KEY, school_id TEXT NOT NULL, name TEXT NOT NULL, sport TEXT NOT NULL,
    level TEXT NOT NULL, FOREIGN KEY(school_id) REFERENCES schools(school_id)
);
CREATE TABLE IF NOT EXISTS schedules (
    schedule_id TEXT PRIMARY KEY, school_id TEXT NOT NULL, team_id TEXT NOT NULL, season TEXT NOT NULL,
    current_version INTEGER NOT NULL, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedule_versions (
    schedule_id TEXT NOT NULL, version INTEGER NOT NULL, source_type TEXT NOT NULL, source_name TEXT NOT NULL,
    source_file_hash TEXT NOT NULL, uploaded_by TEXT NOT NULL, uploaded_at REAL NOT NULL,
    effective_at REAL NOT NULL, supersedes_version INTEGER, status TEXT NOT NULL,
    PRIMARY KEY(schedule_id, version)
);
CREATE TABLE IF NOT EXISTS schedule_events (
    schedule_id TEXT NOT NULL, version INTEGER NOT NULL, schedule_event_id TEXT NOT NULL,
    opponent TEXT NOT NULL, start_at REAL NOT NULL, location TEXT NOT NULL, home_away TEXT NOT NULL,
    source_row INTEGER, PRIMARY KEY(schedule_id, version, schedule_event_id)
);
CREATE TABLE IF NOT EXISTS archive_objects (
    archive_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, school_id TEXT NOT NULL, team_id TEXT NOT NULL,
    season TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, thumbnail TEXT, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lease_records (
    lease_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, member_id TEXT NOT NULL, session_id TEXT NOT NULL,
    rights_version INTEGER NOT NULL, permitted_use TEXT NOT NULL, status TEXT NOT NULL,
    issued_at REAL NOT NULL, hard_expiry REAL NOT NULL, close_reason TEXT
);
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, entity TEXT NOT NULL, source_service TEXT NOT NULL,
    subject_id TEXT, actor_type TEXT NOT NULL, actor_id TEXT, occurred_at REAL NOT NULL, recorded_at REAL NOT NULL,
    payload_version TEXT NOT NULL, payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
    previous_event_hash TEXT, correlation_id TEXT, verification_ref TEXT, rights_version TEXT, legal_effect TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS xrpl_publications (
    publication_id TEXT PRIMARY KEY, audit_event_id TEXT NOT NULL, payload_hash TEXT NOT NULL, manifest_hash TEXT NOT NULL,
    xrpl_account TEXT, xrpl_transaction_hash TEXT, ledger_index TEXT, submitted_at REAL, validated_at REAL,
    status TEXT NOT NULL, error_code TEXT, retry_count INTEGER NOT NULL DEFAULT 0, simulated INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_member_sessions_member ON member_sessions(member_id, status);
CREATE INDEX IF NOT EXISTS idx_schedule_events_schedule ON schedule_events(schedule_id, version, start_at);
CREATE INDEX IF NOT EXISTS idx_audit_events_subject ON audit_events(subject_id, occurred_at);

CREATE TABLE IF NOT EXISTS view_sessions (
    session_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    pseudonym TEXT NOT NULL,
    lease_id TEXT NOT NULL,
    rights_id INTEGER,
    rights_version INTEGER NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL,
    last_seq INTEGER NOT NULL DEFAULT 0,
    last_heartbeat_at REAL,
    qualified_seconds REAL NOT NULL DEFAULT 0,
    state TEXT NOT NULL,
    close_reason TEXT,
    digest TEXT,
    canonical_json TEXT,
    property_id TEXT
);
CREATE TABLE IF NOT EXISTS viewing_heartbeats (
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    playing INTEGER NOT NULL,
    page_visible INTEGER NOT NULL,
    position_seconds REAL,
    credited_seconds REAL NOT NULL DEFAULT 0,
    ts REAL NOT NULL,
    PRIMARY KEY(session_id, seq)
);
CREATE TABLE IF NOT EXISTS webhook_inbox (
    input_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    ts TEXT NOT NULL,
    received_at REAL NOT NULL,
    PRIMARY KEY(input_id, event_type, ts)
);
CREATE TABLE IF NOT EXISTS settlements (
    settlement_id TEXT PRIMARY KEY,
    property_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    period_start REAL,
    period_end REAL,
    session_count INTEGER NOT NULL,
    qualified_seconds REAL NOT NULL,
    manifest_json TEXT NOT NULL,
    manifest_digest TEXT NOT NULL,
    merkle_root TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settlement_leaves (
    settlement_id TEXT NOT NULL,
    leaf_index INTEGER NOT NULL,
    session_id TEXT NOT NULL,
    digest TEXT NOT NULL,
    proof_json TEXT NOT NULL,
    PRIMARY KEY(settlement_id, leaf_index)
);
CREATE TABLE IF NOT EXISTS xrpl_publication_queue (
    publication_id TEXT PRIMARY KEY,
    settlement_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    tx_hash TEXT,
    ledger_index TEXT,
    simulated INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    commitment TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_analytics_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    video_id TEXT,
    window_start REAL,
    window_end REAL,
    provider_minutes REAL,
    tz_qualified_seconds REAL,
    variance_seconds REAL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_view_sessions_event ON view_sessions(event_id, state);
CREATE INDEX IF NOT EXISTS idx_settlements_property ON settlements(property_id, created_at);
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
            user_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(users)").fetchall()}
            if "password_hash" not in user_cols:
                self._conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''")
            if "properties" not in user_cols:
                self._conn.execute("ALTER TABLE users ADD COLUMN properties TEXT NOT NULL DEFAULT '[]'")
            event_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(events)").fetchall()}
            event_alters = {
                "media_provider": "TEXT NOT NULL DEFAULT 'demo'",
                "provider_input_id": "TEXT",
                "provider_video_id": "TEXT",
                "provider_replay_video_id": "TEXT",
                "provider_state": "TEXT NOT NULL DEFAULT ''",
                "provider_last_webhook_at": "REAL",
                "provider_last_error": "TEXT",
                "replay_pending": "INTEGER NOT NULL DEFAULT 0",
                "property_id": "TEXT",
            }
            for name, decl in event_alters.items():
                if name not in event_cols:
                    self._conn.execute(f"ALTER TABLE events ADD COLUMN {name} {decl}")
            self._dedupe_open_view_sessions()
            # Created after dedupe so existing pilot DBs with raced duplicates can migrate.
            self._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_view_sessions_one_open "
                "ON view_sessions(event_id, user_id) WHERE state='open'"
            )
            self._conn.commit()

    def _dedupe_open_view_sessions(self) -> None:
        """Close duplicate open sessions so the unique partial index can be created."""
        dupes = self._conn.execute(
            "SELECT event_id, user_id FROM view_sessions WHERE state='open' "
            "GROUP BY event_id, user_id HAVING COUNT(*) > 1"
        ).fetchall()
        for event_id, user_id in dupes:
            rows = self._conn.execute(
                "SELECT session_id FROM view_sessions "
                "WHERE event_id=? AND user_id=? AND state='open' ORDER BY started_at ASC, session_id ASC",
                (event_id, user_id),
            ).fetchall()
            # Keep the earliest open session; close the rest as duplicates.
            for row in rows[1:]:
                self._conn.execute(
                    "UPDATE view_sessions SET state='closed', close_reason='duplicate_open', "
                    "ended_at=? WHERE session_id=? AND state='open'",
                    (time.time(), row[0]),
                )

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

    def write_transaction(self, fn):
        """Run ``fn(conn)`` under the process lock and commit once.

        Use this for check-then-write paths that must not release the lock between
        statements (ThreadingHTTPServer shares one Database across request threads).
        The unique partial index on open view sessions remains the cross-process backstop.
        """
        with self._lock:
            try:
                result = fn(self._conn)
                self._conn.commit()
                return result
            except Exception:
                self._conn.rollback()
                raise

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
