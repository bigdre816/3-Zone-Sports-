"""Isolated SQLite store for ``ai_jobs`` (AI work leases only).

Does not open, write, or migrate ControlPlane ``lease_records`` / rights /
score / settlement / XRPL tables. Playback leases stay on ControlPlane.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any

from threezone_ai.jobs.types import AiJob

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_jobs (
    job_id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    source_asset_id TEXT,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT,
    result_schema_ref TEXT,
    publish INTEGER NOT NULL DEFAULT 0,
    treasure_release INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    lease_owner TEXT,
    lease_expires_at REAL,
    lineage_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_jobs_status ON ai_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_ai_jobs_lease ON ai_jobs(lease_owner, lease_expires_at);
"""


def _dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, separators=(",", ":"), sort_keys=True)


def _loads(text: str | None, default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default


def _row_to_job(row: sqlite3.Row) -> AiJob:
    return AiJob(
        job_id=row["job_id"],
        task_type=row["task_type"],
        source_asset_id=row["source_asset_id"],
        status=row["status"],
        payload=_loads(row["payload_json"], {}) or {},
        result=_loads(row["result_json"], None),
        result_schema_ref=row["result_schema_ref"],
        publish=False,
        treasure_release=False,
        created_at=float(row["created_at"] or 0),
        updated_at=float(row["updated_at"] or 0),
        lease_owner=row["lease_owner"],
        lease_expires_at=(
            None if row["lease_expires_at"] is None else float(row["lease_expires_at"])
        ),
        lineage_id=row["lineage_id"],
    )


class AiJobStore:
    """Thread-safe SQLite store for durable AI jobs + worker leases."""

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

    def insert(self, job: AiJob) -> AiJob:
        with self._lock:
            self._conn.execute(
                "INSERT INTO ai_jobs("
                "job_id, task_type, source_asset_id, status, payload_json, result_json,"
                " result_schema_ref, publish, treasure_release, created_at, updated_at,"
                " lease_owner, lease_expires_at, lineage_id"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    job.job_id,
                    job.task_type,
                    job.source_asset_id,
                    job.status,
                    _dumps(job.payload),
                    None if job.result is None else _dumps(job.result),
                    job.result_schema_ref,
                    0,
                    0,
                    job.created_at,
                    job.updated_at,
                    job.lease_owner,
                    job.lease_expires_at,
                    job.lineage_id,
                ),
            )
            self._conn.commit()
        return job

    def get(self, job_id: str) -> AiJob | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM ai_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        return _row_to_job(row) if row else None

    def list_jobs(self, *, status: str | None = None, limit: int = 50) -> list[AiJob]:
        sql = "SELECT * FROM ai_jobs"
        params: tuple[Any, ...] = ()
        if status:
            sql += " WHERE status=?"
            params = (status,)
        sql += " ORDER BY created_at ASC LIMIT ?"
        params = params + (int(limit),)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_job(r) for r in rows]

    def claim(
        self,
        job_id: str,
        worker_id: str,
        *,
        now: float,
        expires_at: float,
    ) -> AiJob | None:
        """CAS claim / reclaim of an AI work lease. Returns None on conflict."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE ai_jobs SET lease_owner=?, lease_expires_at=?, status='leased',"
                " updated_at=?"
                " WHERE job_id=?"
                " AND status NOT IN ('succeeded','failed','cancelled')"
                " AND ("
                "   lease_owner IS NULL"
                "   OR lease_owner=?"
                "   OR lease_expires_at IS NULL"
                "   OR lease_expires_at < ?"
                " )",
                (worker_id, expires_at, now, job_id, worker_id, now),
            )
            self._conn.commit()
            if cur.rowcount != 1:
                return None
        return self.get(job_id)

    def heartbeat(
        self,
        job_id: str,
        worker_id: str,
        *,
        now: float,
        expires_at: float,
    ) -> AiJob | None:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE ai_jobs SET lease_expires_at=?, updated_at=?"
                " WHERE job_id=? AND lease_owner=?"
                " AND status IN ('leased','running')"
                " AND lease_expires_at IS NOT NULL"
                " AND lease_expires_at >= ?",
                (expires_at, now, job_id, worker_id, now),
            )
            self._conn.commit()
            if cur.rowcount != 1:
                return None
        return self.get(job_id)

    def mark_running(self, job_id: str, worker_id: str, *, now: float) -> AiJob | None:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE ai_jobs SET status='running', updated_at=?"
                " WHERE job_id=? AND lease_owner=?"
                " AND status IN ('leased','running')"
                " AND lease_expires_at IS NOT NULL"
                " AND lease_expires_at >= ?",
                (now, job_id, worker_id, now),
            )
            self._conn.commit()
            if cur.rowcount != 1:
                return None
        return self.get(job_id)

    def complete(
        self,
        job_id: str,
        *,
        now: float,
        status: str,
        result: dict[str, Any] | None,
        result_schema_ref: str | None,
        lineage_id: str | None,
    ) -> AiJob | None:
        if status not in ("succeeded", "failed", "cancelled"):
            raise ValueError(f"invalid terminal status: {status}")
        with self._lock:
            cur = self._conn.execute(
                "UPDATE ai_jobs SET status=?, result_json=?, result_schema_ref=?,"
                " lineage_id=?, publish=0, treasure_release=0, updated_at=?"
                " WHERE job_id=? AND status NOT IN ('succeeded','failed','cancelled')",
                (
                    status,
                    None if result is None else _dumps(result),
                    result_schema_ref,
                    lineage_id,
                    now,
                    job_id,
                ),
            )
            self._conn.commit()
            if cur.rowcount != 1:
                return None
        return self.get(job_id)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
