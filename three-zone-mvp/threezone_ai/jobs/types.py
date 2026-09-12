"""Y3 — AI work job / worker-lease types (NOT sports playback leases).

Playback / rights leases live on ControlPlane ``lease_records``. This module
is only for durable AI jobs (transcription first) and their worker leases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Allowlisted AI tasks that may be admitted / run in Y3.
ADMIT_TASKS = frozenset({"transcription"})

# Worker-lease TTL (seconds). Bounded so a stale worker cannot hold forever.
DEFAULT_LEASE_TTL_S = 60.0
MIN_LEASE_TTL_S = 5.0
MAX_LEASE_TTL_S = 300.0

# Result summary schema ref (mirrors Y2 typed segments; do not import providers).
TRANSCRIPTION_SEGMENTS_SCHEMA_REF = "threezone.transcription.segments.v0"

STATUSES = (
    "queued",
    "admitted",
    "leased",
    "running",
    "succeeded",
    "failed",
    "cancelled",
)

TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
CLAIMABLE_STATUSES = frozenset({"queued", "admitted", "leased", "running"})


class AiJobError(Exception):
    """Service-level AI job error. ``status`` is an HTTP hint only."""

    status = 400
    code = "ai_job_error"

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class AiDisabled(AiJobError):
    status = 503
    code = "ai_disabled"


class TaskNotAllowlisted(AiJobError):
    status = 400
    code = "task_not_allowlisted"


class JobNotFound(AiJobError):
    status = 404
    code = "job_not_found"


class LeaseConflict(AiJobError):
    """Another worker holds a live AI work lease (double-claim)."""

    status = 409
    code = "ai_work_lease_conflict"


class InvalidWorkLease(AiJobError):
    """Caller does not hold a valid AI work / worker lease."""

    status = 409
    code = "invalid_ai_work_lease"


class JobConflict(AiJobError):
    status = 409
    code = "job_conflict"


@dataclass
class AiJob:
    """Durable AI job row. ``lease_*`` is the AI worker lease, not playback."""

    job_id: str
    task_type: str
    source_asset_id: str | None
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    result_schema_ref: str | None = None
    publish: bool = False
    treasure_release: bool = False
    created_at: float = 0.0
    updated_at: float = 0.0
    lease_owner: str | None = None
    lease_expires_at: float | None = None
    lineage_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "task_type": self.task_type,
            "source_asset_id": self.source_asset_id,
            "status": self.status,
            "payload": dict(self.payload or {}),
            "result": dict(self.result) if isinstance(self.result, dict) else self.result,
            "result_schema_ref": self.result_schema_ref,
            "publish": False,
            "treasure_release": False,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "lease_owner": self.lease_owner,
            "lease_expires_at": self.lease_expires_at,
            "lineage_id": self.lineage_id,
            # Explicit naming so callers do not confuse with playback leases.
            "lease_kind": "ai_work_lease",
        }
