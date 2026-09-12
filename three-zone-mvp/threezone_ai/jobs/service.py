"""Y3 — admit / lease / complete durable AI jobs.

Gateway-only execution: the runner calls ``threezone_ai.gateway.run`` for
allowlisted tasks (transcription first). Never imports Groq/Gemini/Ollama/CF
SDKs or ``threezone_ai.providers.*``.

Successful transcription may emit an immutable proposal (Y4) — proposal ≠
Treasure release (Y5).

This is NOT the sports playback lease (``lease_records`` / ControlPlane).
Worker claims are ``ai_work_lease`` rows on ``ai_jobs``.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from threezone_ai.config import process_ai_enabled
from threezone_ai.jobs.store import AiJobStore
from threezone_ai.jobs.types import (
    ADMIT_TASKS,
    DEFAULT_LEASE_TTL_S,
    MAX_LEASE_TTL_S,
    MIN_LEASE_TTL_S,
    TRANSCRIPTION_SEGMENTS_SCHEMA_REF,
    AiDisabled,
    AiJob,
    AiJobError,
    InvalidWorkLease,
    JobConflict,
    JobNotFound,
    LeaseConflict,
    TaskNotAllowlisted,
)
from threezone_ai.types import AIRequest, AIResponse, TaskType

GatewayRun = Callable[..., AIResponse]


def _now(now: float | None) -> float:
    return float(now if now is not None else time.time())


def _new_job_id() -> str:
    return f"aij_{uuid.uuid4().hex[:16]}"


def bound_lease_ttl_s(ttl_s: float | int | None) -> float:
    if ttl_s is None:
        return DEFAULT_LEASE_TTL_S
    try:
        ttl = float(ttl_s)
    except (TypeError, ValueError):
        return DEFAULT_LEASE_TTL_S
    if ttl != ttl:  # NaN
        return DEFAULT_LEASE_TTL_S
    return max(MIN_LEASE_TTL_S, min(MAX_LEASE_TTL_S, ttl))


def _normalize_task(task_type: TaskType | str) -> str:
    if isinstance(task_type, TaskType):
        return task_type.value
    return str(task_type or "").strip().lower()


def _require_ai_enabled() -> None:
    if not process_ai_enabled():
        raise AiDisabled("AI jobs disabled (THREEZONE_AI_ENABLED process gate)")


def _require_allowlisted(task: str) -> None:
    if task not in ADMIT_TASKS:
        raise TaskNotAllowlisted(
            f"task {task!r} is not allowlisted for AI job admission"
        )


def _summary_from_response(resp: AIResponse, task: str) -> dict[str, Any]:
    meta = dict(resp.metadata or {})
    schema_ref = (
        meta.get("schema_version")
        or meta.get("schema_ref")
        or (TRANSCRIPTION_SEGMENTS_SCHEMA_REF if task == "transcription" else None)
    )
    segments = list(resp.segments or [])
    out: dict[str, Any] = {
        "ok": bool(resp.ok),
        "provider": resp.provider,
        "task_type": resp.task_type,
        "schema_version": schema_ref,
        "segment_count": len(segments),
        "publish": False,
        "treasure_release": False,
        "human_review_required": bool(resp.human_review_required),
        "degraded": bool(resp.degraded),
        "error": resp.error,
        "model": resp.model,
        "version": resp.version,
    }
    if task == "transcription":
        out["segments"] = segments
        out["local_path"] = bool(meta.get("local_path") or meta.get("is_local"))
    return out


class AiJobService:
    """Admit / claim / heartbeat / run / complete AI work jobs."""

    def __init__(
        self,
        store: AiJobStore | None = None,
        *,
        gateway_run: GatewayRun | None = None,
        propose_service: Any | None = None,
        auto_propose: bool = False,
    ) -> None:
        self.store = store or AiJobStore(":memory:")
        self._gateway_run = gateway_run
        self._propose_service = propose_service
        self.auto_propose = auto_propose

    def _run_gateway(self, request: AIRequest, **kwargs: Any) -> AIResponse:
        runner = self._gateway_run
        if runner is None:
            from threezone_ai.gateway import run as gateway_run

            runner = gateway_run
        return runner(request, **kwargs)

    def get(self, job_id: str) -> AiJob:
        job = self.store.get(job_id)
        if job is None:
            raise JobNotFound(f"ai job not found: {job_id}")
        return job

    def admit(
        self,
        task_type: TaskType | str,
        source_asset_id: str | None,
        *,
        payload: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> AiJob:
        """Create a durable job if AI is enabled and the task is allowlisted."""
        _require_ai_enabled()
        task = _normalize_task(task_type)
        _require_allowlisted(task)
        source = (source_asset_id or "").strip() or None
        if task == "transcription" and not source:
            raise AiJobError("source_asset_id required for transcription", "bad_request")
        ts = _now(now)
        job = AiJob(
            job_id=_new_job_id(),
            task_type=task,
            source_asset_id=source,
            status="admitted",
            payload=dict(payload or {}),
            publish=False,
            treasure_release=False,
            created_at=ts,
            updated_at=ts,
        )
        return self.store.insert(job)

    def claim(
        self,
        job_id: str,
        worker_id: str,
        *,
        ttl_s: float | int | None = None,
        now: float | None = None,
    ) -> AiJob:
        """Claim an AI work lease. Double-claim while live is blocked; expired is reclaimable."""
        _require_ai_enabled()
        owner = str(worker_id or "").strip()
        if not owner:
            raise AiJobError("worker_id required", "bad_request")
        existing = self.get(job_id)
        ts = _now(now)
        ttl = bound_lease_ttl_s(ttl_s)
        claimed = self.store.claim(job_id, owner, now=ts, expires_at=ts + ttl)
        if claimed is None:
            live = (
                existing.lease_owner
                and existing.lease_expires_at is not None
                and existing.lease_expires_at >= ts
                and existing.lease_owner != owner
            )
            if live:
                raise LeaseConflict(
                    f"ai work lease held by {existing.lease_owner} until "
                    f"{existing.lease_expires_at}"
                )
            raise JobConflict(f"ai job {job_id} is not claimable ({existing.status})")
        return claimed

    def heartbeat(
        self,
        job_id: str,
        worker_id: str,
        *,
        ttl_s: float | int | None = None,
        now: float | None = None,
    ) -> AiJob:
        """Renew an AI work lease held by ``worker_id``."""
        _require_ai_enabled()
        owner = str(worker_id or "").strip()
        if not owner:
            raise AiJobError("worker_id required", "bad_request")
        self.get(job_id)  # 404 if missing
        ts = _now(now)
        ttl = bound_lease_ttl_s(ttl_s)
        renewed = self.store.heartbeat(job_id, owner, now=ts, expires_at=ts + ttl)
        if renewed is None:
            raise InvalidWorkLease("ai work lease expired or not owned by worker")
        return renewed

    def run(
        self,
        job_id: str,
        worker_id: str,
        *,
        now: float | None = None,
        record_lineage: bool = False,
        config_overlay: dict[str, Any] | None = None,
    ) -> AiJob:
        """Execute an allowlisted AI job via the gateway while holding a work lease."""
        _require_ai_enabled()
        owner = str(worker_id or "").strip()
        if not owner:
            raise AiJobError("worker_id required", "bad_request")
        job = self.get(job_id)
        _require_allowlisted(job.task_type)
        ts = _now(now)
        running = self.store.mark_running(job_id, owner, now=ts)
        if running is None:
            raise InvalidWorkLease("valid ai work lease required to run")

        try:
            task = TaskType(job.task_type)
            req = AIRequest(
                task_type=task,
                source_asset_id=job.source_asset_id,
                asset_ref=(job.payload or {}).get("asset_ref") or job.source_asset_id,
                privacy_class=(job.payload or {}).get("privacy_class") or "member",
                cost_ceiling=(job.payload or {}).get("cost_ceiling") or "any",
                language=(job.payload or {}).get("language"),
                require_human_review=True,
                metadata={
                    "job_id": job.job_id,
                    "publish": False,
                    "treasure_release": False,
                    **dict((job.payload or {}).get("metadata") or {}),
                },
                trace_id=(job.payload or {}).get("trace_id") or job.job_id,
            )
            resp = self._run_gateway(
                req,
                record_lineage=record_lineage,
                **({"config_overlay": config_overlay} if config_overlay is not None else {}),
            )
        except TaskNotAllowlisted:
            raise
        except Exception as exc:
            return self.fail(job_id, owner, f"{type(exc).__name__}: {exc}", now=_now(now))
        return self._finish_from_response(job_id, resp, now=_now(now))

    def complete(
        self,
        job_id: str,
        worker_id: str,
        *,
        result: dict[str, Any] | None = None,
        result_schema_ref: str | None = None,
        lineage_id: str | None = None,
        now: float | None = None,
    ) -> AiJob:
        """Store a result summary. ``publish`` and Treasure-release stay false."""
        _require_ai_enabled()
        owner = str(worker_id or "").strip()
        if not owner:
            raise AiJobError("worker_id required", "bad_request")
        job = self.get(job_id)
        ts = _now(now)
        if job.lease_owner != owner:
            raise InvalidWorkLease("complete requires the holding worker")
        if job.lease_expires_at is None or job.lease_expires_at < ts:
            raise InvalidWorkLease("ai work lease expired")
        if job.status not in ("leased", "running"):
            raise JobConflict(f"ai job {job_id} is not completable ({job.status})")
        summary = dict(result or {})
        summary["publish"] = False
        summary["treasure_release"] = False
        schema = result_schema_ref or summary.get("schema_version")
        if job.task_type == "transcription":
            schema = schema or TRANSCRIPTION_SEGMENTS_SCHEMA_REF
            summary.setdefault("schema_version", schema)
        finished = self.store.complete(
            job_id,
            now=ts,
            status="succeeded",
            result=summary,
            result_schema_ref=schema,
            lineage_id=lineage_id or job.lineage_id,
        )
        if finished is None:
            raise JobConflict(f"ai job {job_id} already terminal")
        return self._maybe_auto_propose(finished, now=ts)

    def fail(
        self,
        job_id: str,
        worker_id: str,
        error: str,
        *,
        now: float | None = None,
    ) -> AiJob:
        _require_ai_enabled()
        job = self.get(job_id)
        owner = str(worker_id or "").strip()
        if job.lease_owner != owner:
            raise InvalidWorkLease("fail requires the holding worker")
        finished = self.store.complete(
            job_id,
            now=_now(now),
            status="failed",
            result={"ok": False, "error": error, "publish": False, "treasure_release": False},
            result_schema_ref=job.result_schema_ref,
            lineage_id=job.lineage_id,
        )
        if finished is None:
            raise JobConflict(f"ai job {job_id} already terminal")
        return finished

    def _propose_service_or_none(self):
        if self._propose_service is not None:
            return self._propose_service
        try:
            from threezone_ai.proposals import get_propose_service

            return get_propose_service()
        except Exception:
            return None

    def propose(self, job_id: str, *, now: float | None = None) -> Any:
        """Emit immutable transcription proposal for a succeeded job (Y4)."""
        job = self.get(job_id)
        proposer = self._propose_service_or_none()
        if proposer is None:
            raise AiJobError("propose service unavailable", "propose_unavailable")
        return proposer.propose_from_job(job, now=now)

    def _maybe_auto_propose(self, finished: AiJob, *, now: float) -> AiJob:
        if not self.auto_propose:
            return finished
        if finished.status != "succeeded" or finished.task_type != "transcription":
            return finished
        result = finished.result if isinstance(finished.result, dict) else {}
        if not result.get("segments"):
            return finished
        try:
            prop = self.propose(finished.job_id, now=now)
            # Attach proposal_id onto an ephemeral view (result already sealed in store).
            if isinstance(finished.result, dict) and prop is not None:
                finished.result = dict(finished.result)
                finished.result["proposal_id"] = prop.proposal_id
                finished.result["proposal_schema_ref"] = getattr(
                    prop, "schema_ref", None
                )
        except Exception:
            # Proposal is best-effort on auto path; explicit /propose surfaces errors.
            pass
        return finished

    def _finish_from_response(
        self, job_id: str, resp: AIResponse, *, now: float
    ) -> AiJob:
        job = self.get(job_id)
        summary = _summary_from_response(resp, job.task_type)
        schema = summary.get("schema_version")
        status = "succeeded" if resp.ok else "failed"
        finished = self.store.complete(
            job_id,
            now=now,
            status=status,
            result=summary,
            result_schema_ref=schema,
            lineage_id=resp.lineage_id,
        )
        if finished is None:
            raise JobConflict(f"ai job {job_id} already terminal")
        return self._maybe_auto_propose(finished, now=now)


_default_service: AiJobService | None = None


def get_job_service(*, reload: bool = False) -> AiJobService:
    """Process-wide service (file store in prod; tests should construct their own)."""
    global _default_service
    if _default_service is None or reload:
        import os

        path = (os.environ.get("THREEZONE_AI_JOBS_PATH") or "data/ai_jobs.sqlite").strip() or "data/ai_jobs.sqlite"
        propose = None
        try:
            from threezone_ai.proposals import get_propose_service

            propose = get_propose_service(reload=reload)
        except Exception:
            propose = None
        _default_service = AiJobService(
            AiJobStore(path),
            propose_service=propose,
            auto_propose=True,
        )
    return _default_service


def reset_job_service() -> None:
    global _default_service
    if _default_service is not None:
        try:
            _default_service.store.close()
        except Exception:
            pass
    _default_service = None
