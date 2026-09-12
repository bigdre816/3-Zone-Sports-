"""AI Gateway HTTP routes for THREEZONE (stdlib BaseHTTPRequestHandler mixin).

Wire into ``backend/http_server.py``:

* extend ``_routes()`` with ``*extra_routes()``
* make ``_Handler`` inherit ``AiGatewayHandlers``

Product code calls ``threezone_ai.gateway.run`` / lineage / ``cut_clip`` only —
never ``threezone_ai.providers.*``.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

# Ensure three-zone-mvp root is on sys.path so ``import threezone_ai`` works
# when the package is vendored beside ``backend/``.
_MVP_ROOT = Path(__file__).resolve().parents[1]
if str(_MVP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MVP_ROOT))

try:
    from .control_plane import ControlError
except ImportError:  # standalone / unit tests without full backend package
    class ControlError(Exception):  # type: ignore[no-redef]
        status = 400

        def __init__(self, message: str, code: str = "bad_request") -> None:
            super().__init__(message)
            self.code = code


def ai_enabled() -> bool:
    """Feature flag — default false so production boots safe."""
    return os.environ.get("THREEZONE_AI_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def extra_routes() -> list[tuple[str, re.Pattern[str], str, str]]:
    """Route tuples matching ``http_server._routes()`` style."""
    return [
        ("POST", re.compile(r"^/api/ai/transcribe$"), "h_ai_transcribe", "member"),
        ("POST", re.compile(r"^/api/ai/search$"), "h_ai_search", "member"),
        ("POST", re.compile(r"^/api/ai/clips/cut$"), "h_ai_clips_cut", "member"),
        ("POST", re.compile(r"^/api/ai/complete$"), "h_ai_complete", "member"),
        ("POST", re.compile(r"^/api/ai/lineage/edit$"), "h_ai_lineage_edit", "member"),
        ("POST", re.compile(r"^/api/ai/lineage/approve$"), "h_ai_lineage_approve", "member"),
        ("GET", re.compile(r"^/api/ai/status$"), "h_ai_status", "none"),
        # Y3 — operator/internal AI work jobs (NOT playback leases)
        ("POST", re.compile(r"^/api/ai-jobs$"), "h_ai_jobs_admit", "operator"),
        ("GET", re.compile(r"^/api/ai-jobs/(?P<job_id>aij_[a-z0-9]+)$"), "h_ai_jobs_get", "operator"),
        ("POST", re.compile(r"^/api/ai-jobs/(?P<job_id>aij_[a-z0-9]+)/claim$"), "h_ai_jobs_claim", "operator"),
        ("POST", re.compile(r"^/api/ai-jobs/(?P<job_id>aij_[a-z0-9]+)/heartbeat$"), "h_ai_jobs_heartbeat", "operator"),
        ("POST", re.compile(r"^/api/ai-jobs/(?P<job_id>aij_[a-z0-9]+)/run$"), "h_ai_jobs_run", "operator"),
        ("POST", re.compile(r"^/api/ai-jobs/(?P<job_id>aij_[a-z0-9]+)/complete$"), "h_ai_jobs_complete", "operator"),
        ("POST", re.compile(r"^/api/ai-jobs/(?P<job_id>aij_[a-z0-9]+)/propose$"), "h_ai_jobs_propose", "operator"),
        # Y5 — Treasure delivery + reconcile (transport only; ≠ Path A release)
        ("POST", re.compile(r"^/api/ai-proposals/(?P<proposal_id>aip_[a-z0-9]+)/deliver$"), "h_ai_proposal_deliver", "operator"),
        ("GET", re.compile(r"^/api/ai-proposals/(?P<proposal_id>aip_[a-z0-9]+)/reconcile$"), "h_ai_proposal_reconcile", "operator"),
        # Y6 — Treasure status projections / revision list (read-only; seats in Treasure)
        ("GET", re.compile(r"^/api/ai-proposals/(?P<proposal_id>aip_[a-z0-9]+)/treasure-projections$"), "h_ai_proposal_treasure_projections", "operator"),
        ("GET", re.compile(r"^/api/ai-proposals/(?P<proposal_id>aip_[a-z0-9]+)/revisions$"), "h_ai_proposal_treasure_projections", "operator"),
        ("POST", re.compile(r"^/api/ai-proposals/(?P<proposal_id>aip_[a-z0-9]+)/treasure-receipt$"), "h_ai_proposal_treasure_receipt", "operator"),
        ("GET", re.compile(r"^/api/ai-proposals/(?P<proposal_id>aip_[a-z0-9]+)$"), "h_ai_proposal_get", "operator"),
    ]


def _ai_response_dict(resp: Any) -> dict[str, Any]:
    return {
        "ok": bool(resp.ok),
        "task_type": resp.task_type,
        "provider": resp.provider,
        "text": resp.text,
        "embedding": resp.embedding,
        "labels": resp.labels,
        "segments": resp.segments,
        "model": resp.model,
        "version": resp.version,
        "confidence": resp.confidence,
        "human_review_required": bool(resp.human_review_required),
        "degraded": bool(resp.degraded),
        "fallback_path": list(resp.fallback_path or []),
        "error": resp.error,
        "lineage_id": resp.lineage_id,
        "title_suggestion": resp.title_suggestion,
        "metadata": dict(resp.metadata or {}),
        "trace_id": resp.trace_id,
    }


def _gateway_public_summary() -> dict[str, Any]:
    """Config summary with no secrets / API keys."""
    from threezone_ai.config import get_settings, load_gateway_config

    cfg = load_gateway_config()
    settings = get_settings()
    tasks_out: dict[str, Any] = {}
    for name, tcfg in (cfg.get("tasks") or {}).items():
        if not isinstance(tcfg, dict):
            continue
        tasks_out[str(name)] = {
            "default_order": list(tcfg.get("default_order") or []),
            "human_review_default": bool(tcfg.get("human_review_default", False)),
        }
    privacy_out: dict[str, Any] = {}
    for name, rules in (cfg.get("privacy_rules") or {}).items():
        if not isinstance(rules, dict):
            continue
        privacy_out[str(name)] = {
            "block_providers": list(rules.get("block_providers") or []),
        }
    return {
        "config_enabled": cfg.get("enabled"),
        "tasks": tasks_out,
        "privacy_rules": privacy_out,
        "cost_tiers": {
            str(k): list(v) if isinstance(v, list) else v
            for k, v in (cfg.get("cost_tiers") or {}).items()
        },
        "lineage": {
            "backend": settings.lineage_backend,
            "path_configured": bool(settings.lineage_path),
        },
        "ollama_base_url": settings.ollama_base_url,
        "keys_present": {
            "groq": bool(settings.groq_api_key),
            "gemini": bool(settings.gemini_api_key),
            "cloudflare": bool(
                settings.cloudflare_account_id and settings.cloudflare_api_token
            ),
        },
    }


class AiGatewayHandlers:
    """Mixin for ``_Handler`` — methods use ``self._send_json`` / ``ControlError``."""

    def _require_ai(self) -> bool:
        if ai_enabled():
            return True
        self._send_json(503, {"error": "ai_disabled", "code": "ai_disabled"})
        return False

    def _ai_error(self, exc: BaseException) -> None:
        msg = str(exc).strip() or type(exc).__name__
        self._send_json(500, {"error": msg, "code": "ai_error"})

    def _safe_under_media(self, rel_or_name: str) -> Path:
        """Join ``rel_or_name`` under ``media_dir``; reject path escape."""
        raw = str(rel_or_name or "").strip()
        if not raw:
            raise ControlError("path required", "bad_request")
        if os.path.isabs(raw):
            # Allow absolute only if already under media_dir
            media_root = Path(getattr(self, "media_dir", "data/media")).resolve()
            candidate = Path(raw).resolve()
        else:
            media_root = Path(getattr(self, "media_dir", "data/media")).resolve()
            # Normalize separators; reject .. segments before resolve
            if ".." in Path(raw).parts:
                raise ControlError("path escapes media_dir", "bad_path")
            candidate = (media_root / raw).resolve()
        media_root = Path(getattr(self, "media_dir", "data/media")).resolve()
        try:
            candidate.relative_to(media_root)
        except ValueError as exc:
            raise ControlError("path escapes media_dir", "bad_path") from exc
        return candidate

    # -- handlers ----------------------------------------------------------

    def h_ai_status(self, p, b, u):
        payload: dict[str, Any] = {"enabled": ai_enabled()}
        if ai_enabled():
            try:
                payload["gateway"] = _gateway_public_summary()
            except Exception as exc:
                payload["gateway"] = {"error": str(exc), "code": "ai_error"}
        else:
            payload["gateway"] = None
        self._send_json(200, payload)

    def h_ai_transcribe(self, p, b, u):
        if not self._require_ai():
            return
        try:
            from threezone_ai import AIRequest, TaskType, run

            body = b or {}
            asset_ref = body.get("asset_ref") or body.get("path")
            if not asset_ref:
                raise ControlError("asset_ref or path required", "bad_request")
            privacy = body.get("privacy_class") or "member"
            req = AIRequest(
                task_type=TaskType.CAPTION,
                asset_ref=str(asset_ref),
                source_asset_id=body.get("source_asset_id"),
                privacy_class=privacy,
                cost_ceiling=body.get("cost_ceiling") or "any",
                language=body.get("language"),
                input_text=body.get("input_text") or body.get("text"),
                trace_id=body.get("trace_id"),
                metadata=dict(body.get("metadata") or {}),
            )
            resp = run(req)
            self._send_json(200, _ai_response_dict(resp))
        except ControlError:
            raise
        except Exception as exc:
            self._ai_error(exc)

    def h_ai_search(self, p, b, u):
        if not self._require_ai():
            return
        try:
            from threezone_ai import AIRequest, TaskType, run

            body = b or {}
            text = body.get("text") or body.get("query") or body.get("input_text")
            if not text or not str(text).strip():
                raise ControlError("text required", "bad_request")
            privacy = body.get("privacy_class") or "member"
            req = AIRequest(
                task_type=TaskType.EMBEDDING,
                input_text=str(text),
                privacy_class=privacy,
                cost_ceiling=body.get("cost_ceiling") or "free_only",
                k=body.get("k"),
                trace_id=body.get("trace_id"),
                metadata=dict(body.get("metadata") or {}),
            )
            resp = run(req, record_lineage=False)
            payload = _ai_response_dict(resp)
            payload["hits"] = []
            # Optional in-request documents for a one-shot cosine search
            docs = body.get("documents") or body.get("corpus")
            if resp.ok and resp.embedding and isinstance(docs, list):
                import math

                def _cos(a: list[float], bvec: list[float]) -> float:
                    if not a or not bvec or len(a) != len(bvec):
                        return 0.0
                    dot = sum(x * y for x, y in zip(a, bvec))
                    na = math.sqrt(sum(x * x for x in a))
                    nb = math.sqrt(sum(y * y for y in bvec))
                    if na == 0.0 or nb == 0.0:
                        return 0.0
                    return dot / (na * nb)

                hits = []
                for doc in docs:
                    if not isinstance(doc, dict):
                        continue
                    dvec = doc.get("embedding")
                    if not isinstance(dvec, list):
                        continue
                    hits.append(
                        {
                            "id": doc.get("id"),
                            "score": _cos(resp.embedding, dvec),
                            "text": doc.get("text"),
                            "metadata": dict(doc.get("metadata") or {}),
                        }
                    )
                hits.sort(key=lambda h: h["score"], reverse=True)
                limit = int(body.get("k") or body.get("limit") or 10)
                payload["hits"] = hits[: max(1, limit)]
            self._send_json(200, payload)
        except ControlError:
            raise
        except Exception as exc:
            self._ai_error(exc)

    def h_ai_clips_cut(self, p, b, u):
        if not self._require_ai():
            return
        try:
            from threezone_ai import AIRequest, StudioError, TaskType, cut_clip, run

            body = b or {}
            source_raw = body.get("source_path")
            out_raw = body.get("out_path")
            if not source_raw or not out_raw:
                raise ControlError(
                    "source_path and out_path required", "bad_request"
                )
            try:
                start_s = float(body.get("start_s"))
                end_s = float(body.get("end_s"))
            except (TypeError, ValueError) as exc:
                raise ControlError("start_s and end_s must be numbers", "bad_request") from exc

            source_path = self._safe_under_media(str(source_raw))
            out_path = self._safe_under_media(str(out_raw))

            try:
                written = cut_clip(source_path, start_s, end_s, out_path)
            except StudioError as exc:
                raise ControlError(str(exc), "studio_error") from exc

            result: dict[str, Any] = {
                "ok": True,
                "out_path": str(written),
                "source_path": str(source_path),
                "start_s": start_s,
                "end_s": end_s,
                "title": None,
                "title_ai": None,
            }

            # Optional title via DESCRIPTION (gateway only — never providers)
            title_prompt = body.get("title") or body.get("prompt") or body.get("text")
            if title_prompt:
                privacy = body.get("privacy_class") or "member"
                title_resp = run(
                    AIRequest(
                        task_type=TaskType.DESCRIPTION,
                        input_text=str(title_prompt),
                        privacy_class=privacy,
                        cost_ceiling=body.get("cost_ceiling") or "any",
                        source_asset_id=body.get("source_asset_id"),
                        trace_id=body.get("trace_id"),
                        metadata={
                            "system": "You write concise sports highlight titles.",
                            **dict(body.get("metadata") or {}),
                        },
                    )
                )
                result["title_ai"] = _ai_response_dict(title_resp)
                if title_resp.ok and title_resp.text:
                    result["title"] = title_resp.text.strip().splitlines()[0].strip()[
                        :120
                    ]

            self._send_json(200, result)
        except ControlError:
            raise
        except Exception as exc:
            self._ai_error(exc)

    def h_ai_complete(self, p, b, u):
        if not self._require_ai():
            return
        try:
            from threezone_ai import AIRequest, TaskType, run

            body = b or {}
            prompt = body.get("prompt") or body.get("text") or body.get("input_text")
            if not prompt or not str(prompt).strip():
                raise ControlError("prompt or text required", "bad_request")
            privacy = body.get("privacy_class") or "member"
            req = AIRequest(
                task_type=TaskType.DESCRIPTION,
                input_text=str(prompt),
                privacy_class=privacy,
                cost_ceiling=body.get("cost_ceiling") or "any",
                source_asset_id=body.get("source_asset_id"),
                asset_ref=body.get("asset_ref"),
                trace_id=body.get("trace_id"),
                metadata=dict(body.get("metadata") or {}),
            )
            resp = run(req)
            self._send_json(200, _ai_response_dict(resp))
        except ControlError:
            raise
        except Exception as exc:
            self._ai_error(exc)

    def h_ai_lineage_edit(self, p, b, u):
        if not self._require_ai():
            return
        try:
            from threezone_ai import record_human_edit

            body = b or {}
            output_id = body.get("output_id")
            human_edit = body.get("human_edit") or body.get("edit") or body.get("text")
            if not output_id:
                raise ControlError("output_id required", "bad_request")
            if human_edit is None or str(human_edit).strip() == "":
                raise ControlError("human_edit required", "bad_request")
            editor = body.get("editor")
            if editor is None and isinstance(u, dict):
                editor = u.get("user_id") or u.get("display_name")
            rec = record_human_edit(
                output_id=str(output_id),
                human_edit=str(human_edit),
                editor=editor,
                source_asset_id=body.get("source_asset_id"),
                parent_id=body.get("parent_id"),
                trace_id=body.get("trace_id"),
                metadata=dict(body.get("metadata") or {}),
            )
            self._send_json(200, {"ok": True, "record": rec.to_dict()})
        except ControlError:
            raise
        except Exception as exc:
            self._ai_error(exc)

    def h_ai_lineage_approve(self, p, b, u):
        if not self._require_ai():
            return
        try:
            from threezone_ai import record_approval

            body = b or {}
            output_id = body.get("output_id")
            approved = (
                body.get("approved_final")
                or body.get("approved")
                or body.get("text")
            )
            if not output_id:
                raise ControlError("output_id required", "bad_request")
            if approved is None or str(approved).strip() == "":
                raise ControlError("approved_final required", "bad_request")
            approver = body.get("approver")
            if approver is None and isinstance(u, dict):
                approver = u.get("user_id") or u.get("display_name")
            rec = record_approval(
                output_id=str(output_id),
                approved_final=str(approved),
                approver=approver,
                source_asset_id=body.get("source_asset_id"),
                parent_id=body.get("parent_id"),
                trace_id=body.get("trace_id"),
                metadata=dict(body.get("metadata") or {}),
            )
            self._send_json(200, {"ok": True, "record": rec.to_dict()})
        except ControlError:
            raise
        except Exception as exc:
            self._ai_error(exc)

    def _job_service(self):
        from threezone_ai.jobs import get_job_service

        return get_job_service()

    def _raise_job(self, exc: BaseException) -> None:
        from threezone_ai.jobs.types import AiJobError

        if isinstance(exc, AiJobError):
            err = ControlError(str(exc), exc.code)
            err.status = int(getattr(exc, "status", 400) or 400)
            raise err
        raise exc

    def _job_worker(self, body: dict[str, Any] | None, user: Any) -> str:
        body = body or {}
        worker = body.get("worker_id") or body.get("lease_owner")
        if worker is None and isinstance(user, dict):
            worker = user.get("user_id") or user.get("display_name")
        return str(worker or "").strip()

    def h_ai_jobs_admit(self, p, b, u):
        if not self._require_ai():
            return
        try:
            body = b or {}
            task = body.get("task_type") or "transcription"
            source = body.get("source_asset_id") or body.get("asset_ref")
            job = self._job_service().admit(
                task,
                source,
                payload=dict(body.get("payload") or {}),
            )
            self._send_json(200, {"ok": True, "job": job.to_dict()})
        except ControlError:
            raise
        except Exception as exc:
            from threezone_ai.jobs.types import AiJobError

            if isinstance(exc, AiJobError):
                self._raise_job(exc)
            self._ai_error(exc)

    def h_ai_jobs_get(self, p, b, u):
        if not self._require_ai():
            return
        try:
            job = self._job_service().get((p or {}).get("job_id"))
            self._send_json(200, {"ok": True, "job": job.to_dict()})
        except ControlError:
            raise
        except Exception as exc:
            from threezone_ai.jobs.types import AiJobError

            if isinstance(exc, AiJobError):
                self._raise_job(exc)
            self._ai_error(exc)

    def h_ai_jobs_claim(self, p, b, u):
        if not self._require_ai():
            return
        try:
            body = b or {}
            worker = self._job_worker(body, u)
            job = self._job_service().claim(
                (p or {}).get("job_id"),
                worker,
                ttl_s=body.get("ttl_s") or body.get("ttl"),
            )
            self._send_json(200, {"ok": True, "job": job.to_dict()})
        except ControlError:
            raise
        except Exception as exc:
            from threezone_ai.jobs.types import AiJobError

            if isinstance(exc, AiJobError):
                self._raise_job(exc)
            self._ai_error(exc)

    def h_ai_jobs_heartbeat(self, p, b, u):
        if not self._require_ai():
            return
        try:
            body = b or {}
            worker = self._job_worker(body, u)
            job = self._job_service().heartbeat(
                (p or {}).get("job_id"),
                worker,
                ttl_s=body.get("ttl_s") or body.get("ttl"),
            )
            self._send_json(200, {"ok": True, "job": job.to_dict()})
        except ControlError:
            raise
        except Exception as exc:
            from threezone_ai.jobs.types import AiJobError

            if isinstance(exc, AiJobError):
                self._raise_job(exc)
            self._ai_error(exc)

    def h_ai_jobs_run(self, p, b, u):
        if not self._require_ai():
            return
        try:
            body = b or {}
            worker = self._job_worker(body, u)
            job = self._job_service().run(
                (p or {}).get("job_id"),
                worker,
                record_lineage=bool(body.get("record_lineage")),
            )
            self._send_json(200, {"ok": True, "job": job.to_dict()})
        except ControlError:
            raise
        except Exception as exc:
            from threezone_ai.jobs.types import AiJobError

            if isinstance(exc, AiJobError):
                self._raise_job(exc)
            self._ai_error(exc)

    def h_ai_jobs_complete(self, p, b, u):
        if not self._require_ai():
            return
        try:
            body = b or {}
            worker = self._job_worker(body, u)
            job = self._job_service().complete(
                (p or {}).get("job_id"),
                worker,
                result=dict(body.get("result") or {}),
                result_schema_ref=body.get("result_schema_ref"),
                lineage_id=body.get("lineage_id"),
            )
            self._send_json(200, {"ok": True, "job": job.to_dict()})
        except ControlError:
            raise
        except Exception as exc:
            from threezone_ai.jobs.types import AiJobError

            if isinstance(exc, AiJobError):
                self._raise_job(exc)
            self._ai_error(exc)

    def h_ai_jobs_propose(self, p, b, u):
        """Y4 — immutable transcription proposal (≠ Treasure release)."""
        if not self._require_ai():
            return
        try:
            job_id = (p or {}).get("job_id")
            job = self._job_service().get(job_id)
            from threezone_ai.proposals import ProposeService, get_propose_service
            from threezone_ai.proposals.types import ProposalError

            try:
                proposer = get_propose_service()
            except Exception:
                proposer = ProposeService(job_store=self._job_service().store)
            prop = proposer.propose_from_job(job)
            self._send_json(
                200,
                {
                    "ok": True,
                    "proposal": prop.to_dict(),
                    # Explicit: not Treasure delivery/release (Y5).
                    "treasure_release": False,
                    "publish": False,
                },
            )
        except ControlError:
            raise
        except Exception as exc:
            from threezone_ai.jobs.types import AiJobError
            from threezone_ai.proposals.types import ProposalError

            if isinstance(exc, ProposalError):
                err = ControlError(str(exc), exc.code)
                err.status = int(getattr(exc, "status", 400) or 400)
                raise err
            if isinstance(exc, AiJobError):
                self._raise_job(exc)
            self._ai_error(exc)

    def h_ai_proposal_get(self, p, b, u):
        """Y4/Y5 — fetch immutable proposal (never Treasure release)."""
        if not self._require_ai():
            return
        try:
            from threezone_ai.proposals import get_propose_service
            from threezone_ai.proposals.types import ProposalError

            prop = get_propose_service().get((p or {}).get("proposal_id"))
            self._send_json(
                200,
                {
                    "ok": True,
                    "proposal": prop.to_dict(),
                    "treasure_release": False,
                    "publish": False,
                },
            )
        except Exception as exc:
            from threezone_ai.proposals.types import ProposalError

            if isinstance(exc, ProposalError):
                err = ControlError(str(exc), exc.code)
                err.status = int(getattr(exc, "status", 400) or 400)
                raise err
            self._ai_error(exc)

    def h_ai_proposal_deliver(self, p, b, u):
        """Y5 — deliver proposal to Treasure/Moten intake (transport only).

        Fail-closed when Moten disabled (skipped honest). Never sets
        treasure_release. Status on success is intake_accepted.
        """
        if not self._require_ai():
            return
        try:
            import os

            from threezone_ai.proposals import (
                TreasureDeliveryService,
                get_delivery_service,
                get_propose_service,
            )
            from threezone_ai.proposals.delivery import DeliveryError
            from threezone_ai.proposals.types import ProposalError

            proposal_id = (p or {}).get("proposal_id")
            body = b or {}
            proposer = get_propose_service()
            prop = proposer.get(proposal_id)

            try:
                delivery = get_delivery_service(propose_get=proposer.get)
            except Exception:
                delivery = TreasureDeliveryService(
                    propose_get=proposer.get,
                    moten_service_url=(os.environ.get("TZ_MOTEN_SERVICE_URL") or "").rstrip("/"),
                    moten_shared_secret=os.environ.get("TZ_MOTEN_SHARED_SECRET") or "",
                    moten_timeout_seconds=float(os.environ.get("TZ_MOTEN_TIMEOUT_SECONDS") or "5"),
                )

            producer = body.get("producer") if isinstance(body.get("producer"), dict) else None
            if producer is None and u and isinstance(u, dict):
                producer = {
                    "actor": u.get("username") or u.get("user_id") or u.get("sub"),
                    "role": "producer",
                }
            lineage = body.get("lineage") if isinstance(body.get("lineage"), dict) else None
            force = bool(body.get("force"))

            receipt = delivery.deliver(
                prop, producer=producer, lineage=lineage, force=force, sync=True
            )
            http_status = 202
            if receipt.status == "skipped":
                http_status = 503
            elif receipt.status == "failed":
                http_status = 502
            self._send_json(
                http_status,
                {
                    "ok": receipt.status in ("intake_accepted", "queued", "skipped"),
                    "delivery": receipt.to_dict(),
                    "intake_accepted": receipt.status == "intake_accepted",
                    "treasure_release": False,
                    "publish": False,
                    "governance": "none",
                    "means": "intake_accepted_transport_only"
                    if receipt.status == "intake_accepted"
                    else "transport_pending_or_disabled",
                    "note": "Delivery is transport only; Path A review/release stay in Treasure",
                },
            )
        except Exception as exc:
            from threezone_ai.proposals.delivery import DeliveryError
            from threezone_ai.proposals.types import ProposalError

            if isinstance(exc, (ProposalError, DeliveryError)):
                err = ControlError(str(exc), getattr(exc, "code", "delivery_error"))
                err.status = int(getattr(exc, "status", 400) or 400)
                raise err
            self._ai_error(exc)

    def h_ai_proposal_reconcile(self, p, b, u):
        """Y5 — reconcile local proposal vs last delivery receipt."""
        if not self._require_ai():
            return
        try:
            import os

            from threezone_ai.proposals import (
                TreasureDeliveryService,
                get_delivery_service,
                get_propose_service,
            )
            from threezone_ai.proposals.delivery import DeliveryError
            from threezone_ai.proposals.types import ProposalError

            proposal_id = (p or {}).get("proposal_id")
            proposer = get_propose_service()
            prop = proposer.get(proposal_id)
            try:
                delivery = get_delivery_service(propose_get=proposer.get)
            except Exception:
                delivery = TreasureDeliveryService(
                    propose_get=proposer.get,
                    moten_service_url=(os.environ.get("TZ_MOTEN_SERVICE_URL") or "").rstrip("/"),
                    moten_shared_secret=os.environ.get("TZ_MOTEN_SHARED_SECRET") or "",
                )
            report = delivery.reconcile(prop)
            self._send_json(200, {"ok": True, **report})
        except Exception as exc:
            from threezone_ai.proposals.delivery import DeliveryError
            from threezone_ai.proposals.types import ProposalError

            if isinstance(exc, (ProposalError, DeliveryError)):
                err = ControlError(str(exc), getattr(exc, "code", "delivery_error"))
                err.status = int(getattr(exc, "status", 400) or 400)
                raise err
            self._ai_error(exc)


    def h_ai_proposal_treasure_projections(self, p, b, u):
        """Y6 — list Treasure revision projections for a proposal (read-only).

        Seats stay in Treasure; this is a mirror of status receipts only.
        """
        if not self._require_ai():
            return
        try:
            from threezone_ai.proposals import (
                get_delivery_service,
                get_projection_service,
                get_propose_service,
            )
            from threezone_ai.proposals.projections import ProjectionError
            from threezone_ai.proposals.types import ProposalError

            proposal_id = (p or {}).get("proposal_id")
            proposer = get_propose_service()
            prop = proposer.get(proposal_id)
            try:
                delivery = get_delivery_service(propose_get=proposer.get)
                outbox = delivery.outbox
            except Exception:
                outbox = None
            proj = get_projection_service(
                propose_get=proposer.get, delivery_outbox=outbox
            )
            summary = proj.projection_summary(prop.proposal_id)
            self._send_json(
                200,
                {
                    "ok": True,
                    **summary,
                    "treasure_release": False,
                    "note": "Receipt projections only — not seat assignment or approve",
                },
            )
        except Exception as exc:
            from threezone_ai.proposals.projections import ProjectionError
            from threezone_ai.proposals.types import ProposalError

            if isinstance(exc, (ProposalError, ProjectionError)):
                err = ControlError(str(exc), getattr(exc, "code", "projection_error"))
                err.status = int(getattr(exc, "status", 400) or 400)
                raise err
            self._ai_error(exc)

    def h_ai_proposal_treasure_receipt(self, p, b, u):
        """Y6 — ingest a Treasure status receipt (mock/webhook apply).

        Operator receipt ingest — **not** a seat action / approve endpoint.
        Appends an immutable revision projection and mirrors canonical_* fields.
        """
        if not self._require_ai():
            return
        try:
            from threezone_ai.proposals import (
                get_delivery_service,
                get_projection_service,
                get_propose_service,
            )
            from threezone_ai.proposals.projections import (
                InvalidTreasureReceipt,
                ProjectionError,
            )
            from threezone_ai.proposals.types import ProposalError

            proposal_id = (p or {}).get("proposal_id")
            body = b or {}
            receipt = body.get("receipt") if isinstance(body.get("receipt"), dict) else body
            if not isinstance(receipt, dict):
                raise InvalidTreasureReceipt("JSON receipt object required")

            proposer = get_propose_service()
            prop = proposer.get(proposal_id)
            try:
                delivery = get_delivery_service(propose_get=proposer.get)
                outbox = delivery.outbox
            except Exception:
                outbox = None
            proj = get_projection_service(
                propose_get=proposer.get, delivery_outbox=outbox
            )
            row = proj.apply_treasure_receipt(prop.proposal_id, receipt)
            self._send_json(
                202,
                {
                    "ok": True,
                    "projection": row.to_dict(),
                    "treasure_release": False,
                    "local_release_authority": False,
                    "projection_only": True,
                    "path_a_seats_in_threezone": False,
                    "governance": "treasure_path_a_projection",
                    "means": "receipt_ingest_not_seat_action",
                    "note": "Treasure receipt ingest only — does not assign R1/R2/Release seats",
                },
            )
        except Exception as exc:
            from threezone_ai.proposals.projections import ProjectionError
            from threezone_ai.proposals.types import ProposalError

            if isinstance(exc, (ProposalError, ProjectionError)):
                err = ControlError(str(exc), getattr(exc, "code", "projection_error"))
                err.status = int(getattr(exc, "status", 400) or 400)
                raise err
            self._ai_error(exc)
