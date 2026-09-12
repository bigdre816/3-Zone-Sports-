"""Y4 — immutable transcription proposal types (NOT Treasure release).

A proposal is THREEZONE evidence handoff material. It is never Treasure Path A
release, Moten institutional review, or ControlPlane sports truth.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

PROPOSAL_SCHEMA_REF = "threezone.transcription.proposal.v0"
PROPOSAL_STATUSES = ("proposed",)


class ProposalError(Exception):
    status = 400
    code = "proposal_error"

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class AiDisabledForPropose(ProposalError):
    status = 503
    code = "ai_disabled"


class ProposalNotFound(ProposalError):
    status = 404
    code = "proposal_not_found"


class ProposalImmutable(ProposalError):
    status = 409
    code = "proposal_immutable"


class ProposalConflict(ProposalError):
    status = 409
    code = "proposal_conflict"


class ProposeNotReady(ProposalError):
    status = 409
    code = "propose_not_ready"


def canonical_json(value: Any) -> str:
    """Stable JSON for hashing (sorted keys, compact separators)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash_for_segments(segments: list[dict[str, Any]] | Any) -> str:
    """SHA-256 of canonical segment list JSON."""
    payload = segments if isinstance(segments, list) else list(segments or [])
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


@dataclass
class TranscriptionProposal:
    """Append-only transcription proposal row."""

    proposal_id: str
    job_id: str
    source_asset_id: str | None
    segments: list[dict[str, Any]] = field(default_factory=list)
    content_hash: str = ""
    created_at: float = 0.0
    status: str = "proposed"
    schema_ref: str = PROPOSAL_SCHEMA_REF
    publish: bool = False
    treasure_release: bool = False
    human_review_required: bool = True
    provider: str | None = None
    lineage_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "job_id": self.job_id,
            "source_asset_id": self.source_asset_id,
            "segments": list(self.segments or []),
            "content_hash": self.content_hash,
            "created_at": self.created_at,
            "status": self.status,
            "schema_ref": self.schema_ref,
            "publish": False,
            "treasure_release": False,
            "human_review_required": True,
            "provider": self.provider,
            "lineage_id": self.lineage_id,
            # Explicit: proposal is not Treasure release (Y5).
            "proposal_kind": "transcription_proposal",
            "treasure_status": None,
        }

    def verify_hash(self) -> bool:
        return self.content_hash == content_hash_for_segments(self.segments)
