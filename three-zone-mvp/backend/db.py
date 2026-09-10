"""Database storage for the control plane.

SQLite remains the default local store. Production may point ``TZ_DATABASE_URL``
at PostgreSQL; the compatibility wrapper keeps the existing raw-SQL callers
working without rewriting the service layer.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time

try:  # pragma: no cover - imported in PostgreSQL environments only
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - SQLite-only test/dev environments
    psycopg = None
    dict_row = None

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

-- Source-side delivery outbox. Three-Zone records locally first; a trusted
-- adapter may later submit this canonical source event to Treasure Network.
CREATE TABLE IF NOT EXISTS audit_verification_outbox (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id    INTEGER NOT NULL,
    event_json  TEXT NOT NULL,
    created_at  REAL NOT NULL,
    delivered_at REAL
);
CREATE TABLE IF NOT EXISTS moten_outbox (
    job_id TEXT PRIMARY KEY,
    handoff_type TEXT NOT NULL,
    source_object_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    response_status INTEGER,
    response_body TEXT,
    last_error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
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
CREATE INDEX IF NOT EXISTS idx_moten_outbox_status ON moten_outbox(status, created_at);

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
CREATE TABLE IF NOT EXISTS camera_sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    transport TEXT NOT NULL CHECK (transport IN ('rtsp', 'onvif')),
    endpoint TEXT NOT NULL,
    username_secret_ref TEXT,
    password_secret_ref TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'pending',
    rights_policy_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS camera_sources_endpoint_uq
    ON camera_sources(endpoint);
CREATE TABLE IF NOT EXISTS camera_secrets (
    secret_ref TEXT PRIMARY KEY,
    secret_value TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS camera_archive_objects (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    storage_key TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    recorded_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS camera_archive_verification_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    delivered_at REAL
);
CREATE INDEX IF NOT EXISTS idx_camera_archive_verify_pending
    ON camera_archive_verification_outbox(delivered_at, id);
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
    deleted_at REAL,
    parent_comment_id TEXT
);
CREATE TABLE IF NOT EXISTS member_settings (
    profile_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE,
    show_watching_to_friends INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS team_follows (
    profile_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (profile_id, team_id)
);
CREATE TABLE IF NOT EXISTS school_follows (
    profile_id TEXT NOT NULL,
    school_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (profile_id, school_id)
);
CREATE TABLE IF NOT EXISTS friendships (
    friendship_id TEXT PRIMARY KEY,
    member_a_id TEXT NOT NULL,
    member_b_id TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    created_at REAL NOT NULL,
    accepted_at REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_friendships_pair ON friendships(member_a_id, member_b_id);
CREATE TABLE IF NOT EXISTS member_blocks (
    blocker_profile_id TEXT NOT NULL,
    blocked_profile_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (blocker_profile_id, blocked_profile_id)
);
CREATE TABLE IF NOT EXISTS detected_moments (
    moment_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    moment_type TEXT NOT NULL DEFAULT 'play',
    label TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.5,
    signals TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'candidate',
    rights_version INTEGER,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_moments_event ON detected_moments(event_id, start_ms);
CREATE TABLE IF NOT EXISTS moment_signals (
    signal_id TEXT PRIMARY KEY,
    moment_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    value REAL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS watch_parties (
    party_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    host_profile_id TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'friends',
    join_code TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'open',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS watch_party_members (
    party_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    joined_at REAL NOT NULL,
    left_at REAL,
    PRIMARY KEY (party_id, profile_id)
);
CREATE TABLE IF NOT EXISTS watch_party_messages (
    message_id TEXT PRIMARY KEY,
    party_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_party_messages ON watch_party_messages(party_id, created_at);
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

_REPLACE_TABLE_COLUMNS = {
    "users": [
        "user_id", "display_name", "role", "account_state", "subscription",
        "zones", "packages", "destinations", "password_hash", "properties",
    ],
    "lease_records": [
        "lease_id", "event_id", "member_id", "session_id", "rights_version",
        "permitted_use", "status", "issued_at", "hard_expiry", "close_reason",
    ],
}
_REPLACE_CONFLICT_COLUMNS = {
    "users": ["user_id"],
    "lease_records": ["lease_id"],
}
_INTEGRITY_ERRORS = (sqlite3.IntegrityError,)
if psycopg is not None:  # pragma: no branch
    _INTEGRITY_ERRORS = _INTEGRITY_ERRORS + (psycopg.IntegrityError,)


def _postgres_schema() -> str:
    schema = SCHEMA.replace("AUTOINCREMENT", "")
    schema = re.sub(r"\bREAL\b", "DOUBLE PRECISION", schema)
    schema = re.sub(r"INTEGER PRIMARY KEY\s+CHECK\s*\(id = 1\)", "INTEGER PRIMARY KEY CHECK (id = 1)", schema)
    schema = re.sub(r"INTEGER PRIMARY KEY\b", "BIGSERIAL PRIMARY KEY", schema)
    return schema


def _split_sql_script(script: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(current).strip()
            if stmt:
                parts.append(stmt.rstrip(";"))
            current = []
    tail = "\n".join(current).strip()
    if tail:
        parts.append(tail.rstrip(";"))
    return parts


class Database:
    """Thin thread-safe wrapper around a single SQLite or PostgreSQL connection."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._is_postgres = path.startswith(("postgres://", "postgresql://"))
        if self._is_postgres:
            if psycopg is None:
                raise RuntimeError("psycopg is required when TZ_DATABASE_URL points at PostgreSQL")
            self._conn = psycopg.connect(self._normalize_pg_url(path), row_factory=dict_row)
        else:
            if path != ":memory:":
                parent = os.path.dirname(os.path.abspath(path))
                os.makedirs(parent, exist_ok=True)
            self._conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA busy_timeout=5000;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
        self.init_schema()

    @staticmethod
    def _normalize_pg_url(url: str) -> str:
        return "postgresql://" + url[len("postgres://"):] if url.startswith("postgres://") else url

    def _prepare_sql(self, sql: str) -> str:
        if not self._is_postgres:
            return sql
        text = sql.replace("?", "%s")
        upper = text.lstrip().upper()
        if upper.startswith("INSERT OR IGNORE INTO "):
            text = re.sub(r"(?is)^\s*INSERT OR IGNORE INTO\s+", "INSERT INTO ", text, count=1)
            if " ON CONFLICT " not in text.upper():
                text = f"{text} ON CONFLICT DO NOTHING"
        elif upper.startswith("INSERT OR REPLACE INTO "):
            text = self._replace_upsert_sql(text)
        return text

    def _replace_upsert_sql(self, sql: str) -> str:
        match = re.match(
            r"(?is)^\s*INSERT OR REPLACE INTO\s+([a-z_][a-z0-9_]*)(\s*\(([^)]*)\))?\s+VALUES\s*\((.*)\)\s*$",
            sql.strip(),
        )
        if not match:
            raise RuntimeError(f"unsupported PostgreSQL upsert SQL: {sql}")
        table = match.group(1)
        raw_cols = match.group(3)
        values = match.group(4).strip()
        cols = [c.strip() for c in raw_cols.split(",")] if raw_cols else _REPLACE_TABLE_COLUMNS.get(table)
        if not cols:
            raise RuntimeError(f"missing PostgreSQL upsert column map for {table}")
        conflict_cols = _REPLACE_CONFLICT_COLUMNS.get(table)
        if not conflict_cols:
            raise RuntimeError(f"missing PostgreSQL upsert conflict map for {table}")
        updates = ", ".join(f"{col}=EXCLUDED.{col}" for col in cols if col not in conflict_cols)
        return (
            f"INSERT INTO {table}({','.join(cols)}) VALUES ({values}) "
            f"ON CONFLICT ({','.join(conflict_cols)}) DO UPDATE SET {updates}"
        )

    def init_schema(self) -> None:
        with self._lock:
            if self._is_postgres:
                self._init_postgres_schema()
            else:
                self._init_sqlite_schema()

    def _init_sqlite_schema(self) -> None:
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
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_view_sessions_one_open "
            "ON view_sessions(event_id, user_id) WHERE state='open'"
        )
        job_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(upload_jobs)").fetchall()}
        if job_cols and "upload_url" not in job_cols:
            self._conn.execute("ALTER TABLE upload_jobs ADD COLUMN upload_url TEXT")
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_upload_jobs_owner_idem "
            "ON upload_jobs(owner_profile_id, idempotency_key) "
            "WHERE idempotency_key IS NOT NULL"
        )
        comment_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(comments)").fetchall()}
        if comment_cols and "parent_comment_id" not in comment_cols:
            self._conn.execute("ALTER TABLE comments ADD COLUMN parent_comment_id TEXT")
        self._conn.commit()

    def _init_postgres_schema(self) -> None:
        for stmt in _split_sql_script(_postgres_schema()):
            self._conn.execute(stmt)
        self._conn.execute(
            "INSERT INTO socket_metrics(id, connections, per_event, updated_at)"
            " VALUES (1, 0, '{}', 0) ON CONFLICT DO NOTHING"
        )
        self._dedupe_open_view_sessions()
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_view_sessions_one_open "
            "ON view_sessions(event_id, user_id) WHERE state='open'"
        )
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_upload_jobs_owner_idem "
            "ON upload_jobs(owner_profile_id, idempotency_key) "
            "WHERE idempotency_key IS NOT NULL"
        )
        try:
            self._conn.execute("ALTER TABLE comments ADD COLUMN parent_comment_id TEXT")
        except Exception:
            pass
        self._conn.commit()

    def _dedupe_open_view_sessions(self) -> None:
        """Close duplicate open sessions so the unique partial index can be created."""
        dupes = self._conn.execute(
            self._prepare_sql(
                "SELECT event_id, user_id FROM view_sessions WHERE state='open' "
                "GROUP BY event_id, user_id HAVING COUNT(*) > 1"
            )
        ).fetchall()
        for dup in dupes:
            event_id = dup["event_id"] if isinstance(dup, dict) else dup[0]
            user_id = dup["user_id"] if isinstance(dup, dict) else dup[1]
            rows = self._conn.execute(
                self._prepare_sql(
                    "SELECT session_id FROM view_sessions "
                    "WHERE event_id=? AND user_id=? AND state='open' ORDER BY started_at ASC, session_id ASC"
                ),
                (event_id, user_id),
            ).fetchall()
            # Keep the earliest open session; close the rest as duplicates.
            for row in rows[1:]:
                session_id = row["session_id"] if isinstance(row, dict) else row[0]
                self._conn.execute(
                    self._prepare_sql(
                        "UPDATE view_sessions SET state='closed', close_reason='duplicate_open', "
                        "ended_at=? WHERE session_id=? AND state='open'"
                    ),
                    (time.time(), session_id),
                )

    # --- primitives -------------------------------------------------------
    def query(self, sql: str, params: tuple = ()):
        with self._lock:
            return list(self._conn.execute(self._prepare_sql(sql), params).fetchall())

    def query_one(self, sql: str, params: tuple = ()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple = ()) -> int:
        with self._lock:
            prepared = self._prepare_sql(sql)
            wants_id = self._is_postgres and prepared.lstrip().upper().startswith("INSERT INTO AUDIT(")
            cur = self._conn.execute(
                prepared + (" RETURNING id" if wants_id and "RETURNING" not in prepared.upper() else ""),
                params,
            )
            if wants_id:
                row = cur.fetchone()
                self._conn.commit()
                if isinstance(row, dict):
                    return int(row["id"])
                return int(row[0])
            self._conn.commit()
            return getattr(cur, "lastrowid", 0) or 0

    def executemany(self, sql: str, seq) -> None:
        with self._lock:
            self._conn.executemany(self._prepare_sql(sql), seq)
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


IntegrityError = _INTEGRITY_ERRORS
