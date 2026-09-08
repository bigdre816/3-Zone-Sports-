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
    destinations  TEXT NOT NULL DEFAULT '[]',  -- JSON list; ["*"] means all
    password_hash TEXT NOT NULL DEFAULT ''
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

-- Member sports network V1. Auth identity stays on users; public profile is linked.
CREATE TABLE IF NOT EXISTS profiles (
    profile_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE,
    handle TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    avatar TEXT NOT NULL DEFAULT '',
    bio TEXT NOT NULL DEFAULT '',
    market TEXT NOT NULL DEFAULT 'midwest',
    sports TEXT NOT NULL DEFAULT '[]',
    profile_type TEXT NOT NULL DEFAULT 'fan',
    visibility TEXT NOT NULL DEFAULT 'public',
    verification_state TEXT NOT NULL DEFAULT 'none',
    verification_badge TEXT NOT NULL DEFAULT '',
    team_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS follows (
    follower_profile_id TEXT NOT NULL,
    followed_profile_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (follower_profile_id, followed_profile_id)
);
CREATE TABLE IF NOT EXISTS media_assets (
    media_asset_id TEXT PRIMARY KEY,
    owner_profile_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_uid TEXT NOT NULL,
    kind TEXT NOT NULL,
    duration_seconds REAL,
    byte_size INTEGER,
    status TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE (provider, provider_uid)
);
CREATE TABLE IF NOT EXISTS upload_jobs (
    upload_job_id TEXT PRIMARY KEY,
    owner_profile_id TEXT NOT NULL,
    intended_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_uid TEXT,
    upload_token TEXT,
    upload_url TEXT,
    upload_method TEXT NOT NULL,
    status TEXT NOT NULL,
    expected_kind TEXT NOT NULL,
    byte_size INTEGER,
    duration_seconds REAL,
    error_code TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    expires_at REAL NOT NULL,
    idempotency_key TEXT,
    intended_object_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_upload_jobs_owner_idem
    ON upload_jobs(owner_profile_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS provider_webhook_events (
    provider_event_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_uid TEXT,
    event_type TEXT NOT NULL,
    received_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
    post_id TEXT PRIMARY KEY,
    author_profile_id TEXT NOT NULL,
    media_asset_id TEXT,
    clip_id TEXT,
    caption TEXT NOT NULL DEFAULT '',
    sport TEXT NOT NULL DEFAULT 'other',
    visibility TEXT NOT NULL DEFAULT 'public',
    publication_status TEXT NOT NULL DEFAULT 'draft',
    comments_enabled INTEGER NOT NULL DEFAULT 1,
    event_id TEXT,
    created_at REAL NOT NULL,
    published_at REAL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS games (
    game_id TEXT PRIMARY KEY,
    game_number TEXT NOT NULL UNIQUE,
    event_id TEXT,
    sport TEXT NOT NULL,
    home_team_id TEXT,
    away_team_id TEXT,
    home_team_name TEXT NOT NULL DEFAULT '',
    away_team_name TEXT NOT NULL DEFAULT '',
    game_date REAL,
    timezone TEXT NOT NULL DEFAULT 'America/Chicago',
    season TEXT NOT NULL DEFAULT '',
    level TEXT NOT NULL DEFAULT 'other',
    venue TEXT NOT NULL DEFAULT '',
    uploader_profile_id TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'member_upload',
    media_asset_id TEXT,
    processing_status TEXT NOT NULL DEFAULT 'uploading',
    visibility TEXT NOT NULL DEFAULT 'private',
    verification_status TEXT NOT NULL DEFAULT 'pending',
    rights_version INTEGER,
    archive_id TEXT,
    duration_seconds REAL,
    rights_attestation INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS game_media (
    game_id TEXT NOT NULL,
    media_asset_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'source',
    created_at REAL NOT NULL,
    PRIMARY KEY (game_id, media_asset_id)
);
CREATE TABLE IF NOT EXISTS clips (
    clip_id TEXT PRIMARY KEY,
    post_id TEXT,
    creator_profile_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_media_asset_id TEXT,
    source_game_id TEXT,
    start_seconds REAL,
    end_seconds REAL,
    provider_job_id TEXT,
    derived_media_asset_id TEXT,
    caption TEXT NOT NULL DEFAULT '',
    sport TEXT NOT NULL DEFAULT 'other',
    source_rights_version INTEGER,
    rights_decision TEXT NOT NULL DEFAULT 'pending',
    publication_status TEXT NOT NULL DEFAULT 'draft',
    visibility TEXT NOT NULL DEFAULT 'private',
    created_at REAL NOT NULL,
    published_at REAL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reactions (
    reaction_id TEXT PRIMARY KEY,
    actor_profile_id TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'like',
    created_at REAL NOT NULL,
    UNIQUE (actor_profile_id, subject_type, subject_id, kind)
);
CREATE TABLE IF NOT EXISTS comments (
    comment_id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    author_profile_id TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at REAL NOT NULL,
    deleted_at REAL
);
CREATE TABLE IF NOT EXISTS saves (
    profile_id TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (profile_id, subject_type, subject_id)
);
CREATE TABLE IF NOT EXISTS media_shares (
    share_id TEXT PRIMARY KEY,
    sender_profile_id TEXT NOT NULL,
    recipient_profile_id TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    read_at REAL,
    idempotency_key TEXT UNIQUE,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS athlete_tags (
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    PRIMARY KEY (subject_type, subject_id, profile_id)
);
CREATE TABLE IF NOT EXISTS team_tags (
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    PRIMARY KEY (subject_type, subject_id, team_id)
);
CREATE TABLE IF NOT EXISTS notifications (
    notification_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    actor_profile_id TEXT,
    subject_type TEXT,
    subject_id TEXT,
    created_at REAL NOT NULL,
    read_at REAL
);
CREATE TABLE IF NOT EXISTS moderation_cases (
    case_id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    reporter_profile_id TEXT,
    flag_source TEXT NOT NULL,
    classifier_result TEXT NOT NULL,
    policy_decision TEXT,
    reviewer_id TEXT,
    reason TEXT,
    action TEXT,
    strike INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    decided_at REAL
);
CREATE TABLE IF NOT EXISTS content_reports (
    report_id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    reporter_profile_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_profiles_handle ON profiles(handle);
CREATE INDEX IF NOT EXISTS idx_posts_author ON posts(author_profile_id, published_at);
CREATE INDEX IF NOT EXISTS idx_posts_feed ON posts(publication_status, published_at);
CREATE INDEX IF NOT EXISTS idx_games_uploader ON games(uploader_profile_id, created_at);
CREATE INDEX IF NOT EXISTS idx_clips_source_game ON clips(source_game_id);
CREATE INDEX IF NOT EXISTS idx_reactions_subject ON reactions(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_comments_subject ON comments(subject_type, subject_id, created_at);
CREATE INDEX IF NOT EXISTS idx_shares_recipient ON media_shares(recipient_profile_id, created_at);
CREATE INDEX IF NOT EXISTS idx_moderation_open ON moderation_cases(policy_decision, created_at);
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
            cols = {row[1] for row in self._conn.execute("PRAGMA table_info(users)").fetchall()}
            if "password_hash" not in cols:
                self._conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''")
            job_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(upload_jobs)").fetchall()}
            if job_cols and "upload_url" not in job_cols:
                self._conn.execute("ALTER TABLE upload_jobs ADD COLUMN upload_url TEXT")
            self._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_upload_jobs_owner_idem "
                "ON upload_jobs(owner_profile_id, idempotency_key) "
                "WHERE idempotency_key IS NOT NULL"
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
