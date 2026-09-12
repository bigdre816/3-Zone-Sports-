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
