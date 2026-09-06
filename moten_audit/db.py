"""Durable SQLite store for audit, verification, publication, and receipts."""

from __future__ import annotations

import json
import os
import sqlite3
import threading


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS audit_events (
 event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, schema_version TEXT NOT NULL,
 organization_id TEXT NOT NULL, source_system TEXT NOT NULL, object_id TEXT NOT NULL,
 object_version TEXT NOT NULL, occurred_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
 canonical_event_hash TEXT NOT NULL UNIQUE, previous_event_id TEXT, previous_event_hash TEXT,
 classification TEXT NOT NULL, on_chain_policy TEXT NOT NULL, legal_effect TEXT NOT NULL,
 event_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_event_versions (
 event_id TEXT NOT NULL, version INTEGER NOT NULL, canonical_event_hash TEXT NOT NULL,
 event_json TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(event_id, version)
);
CREATE TABLE IF NOT EXISTS audit_event_lineage (
 event_id TEXT PRIMARY KEY, previous_event_id TEXT, previous_event_hash TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_policies (
 event_type TEXT NOT NULL, policy_version TEXT NOT NULL, publication_requirement TEXT NOT NULL,
 publication_mode TEXT NOT NULL, required_fields TEXT NOT NULL, prohibited_fields TEXT NOT NULL,
 classification TEXT NOT NULL, requires_human_approval INTEGER NOT NULL, allowed_signing_profiles TEXT NOT NULL,
 active_from TEXT NOT NULL, active_until TEXT, PRIMARY KEY(event_type, policy_version)
);
CREATE TABLE IF NOT EXISTS verification_records (
 verification_id TEXT PRIMARY KEY, source_event_id TEXT NOT NULL, verification_status TEXT NOT NULL,
 verification_profile TEXT NOT NULL, eligible_for_onchain INTEGER NOT NULL, verification_hash TEXT NOT NULL UNIQUE,
 envelope_json TEXT NOT NULL, received_at TEXT NOT NULL, verified_at TEXT, hold_reason TEXT
);
CREATE TABLE IF NOT EXISTS verification_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT, verification_id TEXT NOT NULL, event_type TEXT NOT NULL,
 detail TEXT NOT NULL, occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS blockchain_publication_requests (
 request_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, verification_id TEXT NOT NULL,
 idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL, publication_mode TEXT NOT NULL,
 signing_profile_id TEXT NOT NULL, network TEXT NOT NULL, approved_representation TEXT NOT NULL,
 hold_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS blockchain_publication_attempts (
 attempt_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, status TEXT NOT NULL, failure_class TEXT,
 result_code TEXT, transaction_hash TEXT, submitted_at TEXT, validated_at TEXT, detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS blockchain_receipts (
 receipt_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, attempt_id TEXT NOT NULL UNIQUE,
 network TEXT NOT NULL, account TEXT, transaction_hash TEXT, ledger_index INTEGER,
 transaction_type TEXT NOT NULL, submitted_at TEXT, validated_at TEXT, result_code TEXT NOT NULL,
 fee TEXT, canonical_event_hash TEXT NOT NULL, memo_hash TEXT, raw_result_reference TEXT,
 status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signing_profiles (
 signing_profile_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, account TEXT, network TEXT NOT NULL,
 status TEXT NOT NULL, effective_at TEXT NOT NULL, signer_role TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signing_authority_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, profile_id TEXT, detail TEXT NOT NULL, occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reconciliation_runs (
 run_id TEXT PRIMARY KEY, status TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT
);
CREATE TABLE IF NOT EXISTS reconciliation_findings (
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, severity TEXT NOT NULL, finding_type TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chain_health_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, detail TEXT NOT NULL, occurred_at TEXT NOT NULL
);
"""


def dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def loads(value: str) -> object:
    return json.loads(value)


class Database:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def execute(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            cursor = self.conn.execute(sql, args)
            self.conn.commit()
            return cursor.lastrowid

    def one(self, sql: str, args: tuple = ()):
        with self.lock:
            return self.conn.execute(sql, args).fetchone()

    def many(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            return list(self.conn.execute(sql, args).fetchall())

