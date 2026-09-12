"""Y4 — emit immutable transcription proposals from succeeded AI jobs.

Proposal ≠ Treasure release (Y5). Gateway-only; never imports providers/SDKs.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

from threezone_ai.config import process_ai_enabled
from threezone_ai.jobs.store import AiJobStore
from threezone_ai.jobs.types import AiJob, JobNotFound
from threezone_ai.proposals.store import AiProposalStore
from threezone_ai.proposals.types import (
    PROPOSAL_SCHEMA_REF,
    AiDisabledForPropose,
    ProposeNotReady,
    ProposalConflict,
    ProposalImmutable,
    ProposalNotFound,
    TranscriptionProposal,
    content_hash_for_segments,
)


def _now(now: float | None) -> float:
    return float(now if now is not None else time.time())


def _new_proposal_id() -> str:
    return f"aip_{uuid.uuid4().hex[:16]}"


def _require_ai_enabled() -> None:
    if not process_ai_enabled():
        raise AiDisabledForPropose(
            "AI proposals disabled (THREEZONE_AI_ENABLED process gate)"
        )


def _segments_from_job(job: AiJob) -> list[dict[str, Any]]:
    result = job.result if isinstance(job.result, dict) else {}
    segs = result.get("segments")
    if isinstance(segs, list) and segs:
        return list(segs)
    payload = job.payload if isinstance(job.payload, dict) else {}
    segs = payload.get("segments")
    if isinstance(segs, list) and segs:
        return list(segs)
    return []


class ProposeService:
    """Create / read immutable transcription proposals from AI jobs."""

    def __init__(
        self,
        store: AiProposalStore | None = None,
        *,
        job_store: AiJobStore | None = None,
    ) -> None:
        self.store = store or AiProposalStore(":memory:")
        self.job_store = job_store

    def get(self, proposal_id: str) -> TranscriptionProposal:
        prop = self.store.get(proposal_id)
        if prop is None:
            raise ProposalNotFound(f"proposal not found: {proposal_id}")
        return prop

    def get_by_job(self, job_id: str) -> TranscriptionProposal | None:
        return self.store.get_by_job(job_id)

    def propose_from_job(
        self,
        job: AiJob,
        *,
        now: float | None = None,
        segments: list[dict[str, Any]] | None = None,
    ) -> TranscriptionProposal:
        """Create append-only proposal from a succeeded transcription job."""
        _require_ai_enabled()
        if job.task_type != "transcription":
            raise ProposeNotReady(
                f"propose only for transcription jobs (got {job.task_type!r})"
            )
        if job.status != "succeeded":
            raise ProposeNotReady(
                f"job {job.job_id} must be succeeded to propose (status={job.status})"
            )
        existing = self.store.get_by_job(job.job_id)
        if existing is not None:
            return existing

        segs = list(segments) if segments is not None else _segments_from_job(job)
        if not segs:
            raise ProposeNotReady(
                f"job {job.job_id} has no segments to propose"
            )
        result = job.result if isinstance(job.result, dict) else {}
        ts = _now(now)
        prop = TranscriptionProposal(
            proposal_id=_new_proposal_id(),
            job_id=job.job_id,
            source_asset_id=job.source_asset_id,
            segments=segs,
            content_hash=content_hash_for_segments(segs),
            created_at=ts,
            status="proposed",
            schema_ref=PROPOSAL_SCHEMA_REF,
            publish=False,
            treasure_release=False,
            human_review_required=True,
            provider=result.get("provider"),
            lineage_id=job.lineage_id,
        )
        try:
            return self.store.insert(prop)
        except Exception as exc:
            # Unique job_id race → return winner
            again = self.store.get_by_job(job.job_id)
            if again is not None:
                return again
            raise ProposalConflict(f"failed to insert proposal: {exc}") from exc

    def propose_job_id(
        self,
        job_id: str,
        *,
        now: float | None = None,
        job: AiJob | None = None,
    ) -> TranscriptionProposal:
        _require_ai_enabled()
        resolved = job
        if resolved is None:
            if self.job_store is None:
                raise ProposeNotReady("job_store required to resolve job_id")
            resolved = self.job_store.get(job_id)
            if resolved is None:
                raise JobNotFound(f"ai job not found: {job_id}")
        return self.propose_from_job(resolved, now=now)

    def mutate_payload(
        self, proposal_id: str, segments: list[dict[str, Any]]
    ) -> None:
        """Explicit mutation API — always rejected (immutability)."""
        prop = self.get(proposal_id)
        from threezone_ai.proposals.types import content_hash_for_segments as _hash

        self.store.update_payload(prop.proposal_id, segments, _hash(segments))


_default_propose: ProposeService | None = None


def get_propose_service(*, reload: bool = False) -> ProposeService:
    global _default_propose
    if _default_propose is None or reload:
        path = (
            os.environ.get("THREEZONE_AI_PROPOSALS_PATH") or "data/ai_proposals.sqlite"
        ).strip() or "data/ai_proposals.sqlite"
        jobs_path = (
            os.environ.get("THREEZONE_AI_JOBS_PATH") or "data/ai_jobs.sqlite"
        ).strip() or "data/ai_jobs.sqlite"
        _default_propose = ProposeService(
            AiProposalStore(path),
            job_store=AiJobStore(jobs_path),
        )
    return _default_propose


def reset_propose_service() -> None:
    global _default_propose
    if _default_propose is not None:
        try:
            _default_propose.store.close()
        except Exception:
            pass
    _default_propose = None
