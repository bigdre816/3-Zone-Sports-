"""Isolated SQLite store for immutable AI transcription proposals (Y4).

Append-only for payload + content_hash. Separate from ControlPlane truth plane
and from ``ai_jobs`` (may share a process but not CP tables).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any

from threezone_ai.proposals.types import (
    PROPOSAL_SCHEMA_REF,
    ProposalImmutable,
    TranscriptionProposal,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_proposals (
    proposal_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE,
    source_asset_id TEXT,
    segments_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    schema_ref TEXT NOT NULL,
    publish INTEGER NOT NULL DEFAULT 0,
    treasure_release INTEGER NOT NULL DEFAULT 0,
    human_review_required INTEGER NOT NULL DEFAULT 1,
    provider TEXT,
    lineage_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_proposals_job ON ai_proposals(job_id);
CREATE INDEX IF NOT EXISTS idx_ai_proposals_created ON ai_proposals(created_at);
"""


def _dumps(value: Any) -> str:
    return json.dumps(value if value is not None else [], separators=(",", ":"), sort_keys=True)


def _loads(text: str | None, default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default


def _row_to_proposal(row: sqlite3.Row) -> TranscriptionProposal:
    return TranscriptionProposal(
        proposal_id=row["proposal_id"],
        job_id=row["job_id"],
        source_asset_id=row["source_asset_id"],
        segments=_loads(row["segments_json"], []) or [],
        content_hash=row["content_hash"],
        created_at=float(row["created_at"] or 0),
        status=row["status"] or "proposed",
        schema_ref=row["schema_ref"] or PROPOSAL_SCHEMA_REF,
        publish=False,
        treasure_release=False,
        human_review_required=True,
        provider=row["provider"],
        lineage_id=row["lineage_id"],
    )


class AiProposalStore:
    """Thread-safe append-only SQLite store for transcription proposals."""

    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self._lock = threading.RLock()
        if path != ":memory:":
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA busy_timeout=5000;")
        self._init()

    def _init(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def insert(self, proposal: TranscriptionProposal) -> TranscriptionProposal:
        with self._lock:
            self._conn.execute(
                "INSERT INTO ai_proposals("
                "proposal_id, job_id, source_asset_id, segments_json, content_hash,"
                " created_at, status, schema_ref, publish, treasure_release,"
                " human_review_required, provider, lineage_id"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    proposal.proposal_id,
                    proposal.job_id,
                    proposal.source_asset_id,
                    _dumps(proposal.segments),
                    proposal.content_hash,
                    proposal.created_at,
                    "proposed",
                    proposal.schema_ref or PROPOSAL_SCHEMA_REF,
                    0,
                    0,
                    1,
                    proposal.provider,
                    proposal.lineage_id,
                ),
            )
            self._conn.commit()
        return proposal

    def get(self, proposal_id: str) -> TranscriptionProposal | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM ai_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
        return _row_to_proposal(row) if row else None

    def get_by_job(self, job_id: str) -> TranscriptionProposal | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM ai_proposals WHERE job_id=?", (job_id,)
            ).fetchone()
        return _row_to_proposal(row) if row else None

    def update_payload(self, proposal_id: str, segments: Any, content_hash: str) -> None:
        """Mutating payload/hash is forbidden — always raises."""
        raise ProposalImmutable(
            f"ai proposal {proposal_id} is append-only; payload/hash cannot be updated"
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
