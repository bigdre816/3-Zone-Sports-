"""L1B — operator-only private live capture sessions.

Lifecycle (server-enforced):
  REQUESTED → CAPTURE_STARTING → VERIFYING_PRIVATE → STOP_REQUESTED → STOPPED
  REQUESTED | CAPTURE_STARTING | VERIFYING_PRIVATE → FAILED

Server-forced truth on create (clients cannot override):
  public_state=LIVE_PRIVATE
  distribution_state=DISABLED
  sports_status=UNVERIFIED
  safety_state=NOT_EVALUATED
  provider_name=local_browser (no Restream / Cloudflare live input)

Does NOT call media_provider, restream, AI, xrpl, settlement, Moten intake,
or ControlPlane.transition(live). Audits via ControlPlane.audit_log only
(no Moten outbox handoff for these events).
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from .config import private_live_capture_enabled
from .control_plane import (
    ConflictError,
    ControlError,
    ControlPlane,
    NotFoundError,
    ValidationError,
    now,
)


class FeatureDisabledError(ControlError):
    """Mirror ai_disabled — HTTP 503 when private live capture flag is off."""
    status = 503

from .db import dumps

# ---------------------------------------------------------------------------
# Constants (L1B — Andre authorization defaults; L0 discovery file missing)
# ---------------------------------------------------------------------------
POLICY_VERSION = "l1b-private-v1"
PROVIDER_NAME = "local_browser"

STATE_REQUESTED = "REQUESTED"
STATE_CAPTURE_STARTING = "CAPTURE_STARTING"
STATE_VERIFYING_PRIVATE = "VERIFYING_PRIVATE"
STATE_STOP_REQUESTED = "STOP_REQUESTED"
STATE_STOPPED = "STOPPED"
STATE_FAILED = "FAILED"

PUBLIC_STATE_LIVE_PRIVATE = "LIVE_PRIVATE"
DISTRIBUTION_DISABLED = "DISABLED"
SPORTS_UNVERIFIED = "UNVERIFIED"
SAFETY_NOT_EVALUATED = "NOT_EVALUATED"

# Fields clients may attempt to set maliciously — always stripped/ignored.
_CLIENT_TRUTH_FIELDS = frozenset({
    "sports_status",
    "sports_confidence",
    "public_state",
    "distribution_state",
    "safety_state",
    "provider_name",
    "provider_stream_id",
    "restream_event_id",
    "rights_version",
    "policy_version",
    "session_state",
    "source_asset_id",
    "source_hash",
    "stop_reason",
    "failure_reason",
    "supersedes_session_id",
    "live_session_id",
    "actor_id",
    "env",
})

_ALLOWED_TRANSITIONS = {
    STATE_REQUESTED: {STATE_CAPTURE_STARTING, STATE_FAILED},
    STATE_CAPTURE_STARTING: {STATE_VERIFYING_PRIVATE, STATE_FAILED},
    STATE_VERIFYING_PRIVATE: {STATE_STOP_REQUESTED, STATE_FAILED},
    STATE_STOP_REQUESTED: {STATE_STOPPED},
    STATE_STOPPED: set(),
    STATE_FAILED: set(),
}

_ACTIVE_STATES = frozenset({
    STATE_REQUESTED,
    STATE_CAPTURE_STARTING,
    STATE_VERIFYING_PRIVATE,
})


def _row_dict(row) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return {k: row[k] for k in row.keys()}


def _fingerprint(payload: dict[str, Any]) -> str:
    """Stable hash of operator-supplied create inputs (after strip)."""
    canon = dumps({
        "event_id": payload.get("event_id") or None,
        "property_id": payload.get("property_id") or None,
        "team_id": payload.get("team_id") or None,
        "supersedes_session_id": payload.get("supersedes_session_id") or None,
    })
    return hashlib.sha256(canon.encode()).hexdigest()


class LiveSessionService:
    """Private live_session lifecycle — operator/owner only."""

    def __init__(self, cp: ControlPlane):
        self.cp = cp
        self.db = cp.db

    # -- auth / flag -------------------------------------------------------
    def require_enabled(self) -> None:
        if not private_live_capture_enabled():
            raise FeatureDisabledError(
                "private live capture disabled",
                "private_live_capture_disabled",
            )

    @staticmethod
    def strip_client_payload(data: dict | None) -> dict[str, Any]:
        raw = dict(data or {})
        for key in _CLIENT_TRUTH_FIELDS:
            raw.pop(key, None)
        return raw

    # -- serialization -----------------------------------------------------
    def _session_dict(self, row) -> dict[str, Any]:
        r = _row_dict(row)
        return {
            "live_session_id": r["live_session_id"],
            "actor_id": r["actor_id"],
            "event_id": r.get("event_id"),
            "property_id": r.get("property_id"),
            "team_id": r.get("team_id"),
            "session_state": r["session_state"],
            "sports_status": r["sports_status"],
            "sports_confidence": r.get("sports_confidence"),
            "public_state": r["public_state"],
            "distribution_state": r["distribution_state"],
            "safety_state": r["safety_state"],
            "rights_version": r.get("rights_version"),
            "policy_version": r.get("policy_version"),
            "source_asset_id": r.get("source_asset_id"),
            "source_hash": r.get("source_hash"),
            "provider_name": r["provider_name"],
            "provider_stream_id": r.get("provider_stream_id"),
            "restream_event_id": r.get("restream_event_id"),
            "stop_reason": r.get("stop_reason"),
            "failure_reason": r.get("failure_reason"),
            "supersedes_session_id": r.get("supersedes_session_id"),
            "idempotency_key": r.get("idempotency_key"),
            "env": r.get("env"),
            "requested_at": r.get("requested_at"),
            "capture_starting_at": r.get("capture_starting_at"),
            "verifying_private_at": r.get("verifying_private_at"),
            "stop_requested_at": r.get("stop_requested_at"),
            "stopped_at": r.get("stopped_at"),
            "failed_at": r.get("failed_at"),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            # Honest operator label — never implies publication.
            "publication": {
                "browser_source_published": False,
                "distribution_state": r["distribution_state"],
                "label": "Private capture session — Browser source not published",
            },
        }

    def _get_row(self, live_session_id: str):
        return self.db.query_one(
            "SELECT * FROM live_sessions WHERE live_session_id=?",
            (live_session_id,),
        )

    def _audit(self, actor_id: str, action: str, live_session_id: str, detail: dict) -> None:
        # Use ControlPlane.audit_log (writes audit + verification outbox).
        # Do NOT call MotenIntakeService / moten_outbox for L1B events.
        self.cp.audit_log(actor_id, action, live_session_id, detail)

    def _transition(self, row, target: str, *, ts_field: str | None = None,
                    extra_sets: dict | None = None) -> Any:
        current = row["session_state"]
        allowed = _ALLOWED_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ConflictError(
                f"illegal live_session transition {current} → {target}",
                "illegal_live_session_transition",
            )
        ts = now()
        sets = ["session_state=?", "updated_at=?"]
        params: list[Any] = [target, ts]
        if ts_field:
            sets.append(f"{ts_field}=?")
            params.append(ts)
        for col, val in (extra_sets or {}).items():
            sets.append(f"{col}=?")
            params.append(val)
        params.append(row["live_session_id"])
        self.db.execute(
            f"UPDATE live_sessions SET {', '.join(sets)} WHERE live_session_id=?",
            tuple(params),
        )
        return self._get_row(row["live_session_id"])

    # -- API ---------------------------------------------------------------
    def start(self, operator: dict, data: dict | None) -> dict:
        """Create (or idempotently return) a private live session.

        Advances synchronously REQUESTED → CAPTURE_STARTING → VERIFYING_PRIVATE
        because L1B has no external provider provisioning — local browser
        preview only, distribution forced DISABLED.
        """
        self.cp.require_operator(operator)
        self.require_enabled()
        payload = self.strip_client_payload(data)
        actor_id = operator["user_id"]
        idem = (payload.get("idempotency_key") or "").strip() or None
        event_id = (payload.get("event_id") or "").strip() or None
        property_id = (payload.get("property_id") or "").strip() or None
        team_id = (payload.get("team_id") or "").strip() or None
        supersedes = (payload.get("supersedes_session_id") or "").strip() or None
        fp = _fingerprint({
            "event_id": event_id,
            "property_id": property_id,
            "team_id": team_id,
            "supersedes_session_id": supersedes,
        })

        if idem:
            existing = self.db.query_one(
                "SELECT * FROM live_sessions WHERE actor_id=? AND idempotency_key=?",
                (actor_id, idem),
            )
            if existing:
                if existing["input_fingerprint"] != fp:
                    raise ConflictError(
                        "idempotency key reuse with different input",
                        "idempotency_conflict",
                    )
                return self._session_dict(existing)

        rights_version = None
        if event_id:
            try:
                self.cp.get_event_row(event_id)
            except NotFoundError:
                raise
            except Exception:
                # get_event_row raises NotFoundError when missing
                raise
            rights = self.cp.current_rights(event_id)
            if rights:
                rights_version = int(rights["version"])
            # Read-only: do NOT mutate event lifecycle / rights / lease / score.

        if supersedes:
            prior = self._get_row(supersedes)
            if not prior:
                raise ValidationError("supersedes_session_id not found", "bad_supersedes")

        sid = "ls_" + uuid.uuid4().hex[:16]
        ts = now()
        env = getattr(self.cp.config, "env", None)

        self.db.execute(
            "INSERT INTO live_sessions("
            "live_session_id, actor_id, event_id, property_id, team_id, "
            "session_state, sports_status, sports_confidence, public_state, "
            "distribution_state, safety_state, rights_version, policy_version, "
            "source_asset_id, source_hash, provider_name, provider_stream_id, "
            "restream_event_id, stop_reason, failure_reason, supersedes_session_id, "
            "idempotency_key, input_fingerprint, env, requested_at, "
            "capture_starting_at, verifying_private_at, stop_requested_at, "
            "stopped_at, failed_at, created_at, updated_at"
            ") VALUES ("
            "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?"
            ")",
            (
                sid, actor_id, event_id, property_id, team_id,
                STATE_REQUESTED, SPORTS_UNVERIFIED, None, PUBLIC_STATE_LIVE_PRIVATE,
                DISTRIBUTION_DISABLED, SAFETY_NOT_EVALUATED, rights_version, POLICY_VERSION,
                None, None, PROVIDER_NAME, None,
                None, None, None, supersedes,
                idem, fp, env, ts,
                None, None, None,
                None, None, ts, ts,
            ),
        )
        row = self._get_row(sid)
        self._audit(actor_id, "live_session.requested", sid, {
            "session_state": STATE_REQUESTED,
            "public_state": PUBLIC_STATE_LIVE_PRIVATE,
            "distribution_state": DISTRIBUTION_DISABLED,
            "event_id": event_id,
            "rights_version": rights_version,
        })

        # Synchronous private capture path — no provider calls.
        row = self._transition(row, STATE_CAPTURE_STARTING, ts_field="capture_starting_at")
        self._audit(actor_id, "live_session.capture_starting", sid, {
            "session_state": STATE_CAPTURE_STARTING,
        })
        row = self._transition(row, STATE_VERIFYING_PRIVATE, ts_field="verifying_private_at")
        self._audit(actor_id, "live_session.verifying_private", sid, {
            "session_state": STATE_VERIFYING_PRIVATE,
            "distribution_state": DISTRIBUTION_DISABLED,
            "browser_source_published": False,
        })
        return self._session_dict(row)

    def get(self, operator: dict, live_session_id: str) -> dict:
        self.cp.require_operator(operator)
        self.require_enabled()
        row = self._get_row(live_session_id)
        if not row:
            # Generic 404 — no existence oracle / metadata leak for guessed IDs.
            raise NotFoundError("live session not found", "live_session_not_found")
        return self._session_dict(row)

    def list_recent(self, operator: dict, limit: int = 20) -> dict:
        """Secret-free recent sessions for the ops health dashboard.

        Does not require the private-capture feature flag (read-only inventory).
        Returns empty lists/counts when the table is missing.
        """
        self.cp.require_operator(operator)
        limit = max(1, min(int(limit or 20), 100))
        safe_fields = (
            "id", "actor_id", "event_id", "session_state", "public_state",
            "distribution_state", "safety_state", "capture_started_at",
            "updated_at", "stop_reason",
        )
        try:
            rows = self.db.query(
                "SELECT live_session_id, actor_id, event_id, session_state, "
                "public_state, distribution_state, safety_state, "
                "capture_starting_at, updated_at, stop_reason "
                "FROM live_sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )
            counts_rows = self.db.query(
                "SELECT session_state, COUNT(*) AS c FROM live_sessions "
                "GROUP BY session_state"
            )
        except Exception:
            return {"recent": [], "by_session_state": {}, "total": 0}

        recent = []
        for r in rows:
            recent.append({
                "id": r["live_session_id"],
                "actor_id": r["actor_id"],
                "event_id": r["event_id"],
                "session_state": r["session_state"],
                "public_state": r["public_state"],
                "distribution_state": r["distribution_state"],
                "safety_state": r["safety_state"],
                "capture_started_at": r["capture_starting_at"],
                "updated_at": r["updated_at"],
                "stop_reason": r["stop_reason"],
            })
        by_state = {row["session_state"]: int(row["c"]) for row in counts_rows}
        total = sum(by_state.values())
        # Keep key order stable for callers that inspect field names.
        _ = safe_fields
        return {"recent": recent, "by_session_state": by_state, "total": total}

    def stop(self, operator: dict, live_session_id: str, data: dict | None = None) -> dict:
        self.cp.require_operator(operator)
        self.require_enabled()
        payload = self.strip_client_payload(data)
        row = self._get_row(live_session_id)
        if not row:
            raise NotFoundError("live session not found", "live_session_not_found")

        # Idempotent stop: already terminal → return as-is.
        if row["session_state"] in (STATE_STOPPED, STATE_STOP_REQUESTED):
            if row["session_state"] == STATE_STOP_REQUESTED:
                row = self._transition(row, STATE_STOPPED, ts_field="stopped_at")
                self._audit(operator["user_id"], "live_session.stopped", live_session_id, {
                    "session_state": STATE_STOPPED,
                    "idempotent": True,
                })
            return self._session_dict(row)
        if row["session_state"] == STATE_FAILED:
            return self._session_dict(row)

        if row["session_state"] not in _ACTIVE_STATES:
            raise ConflictError(
                f"cannot stop live_session in state {row['session_state']}",
                "illegal_live_session_transition",
            )

        reason = (payload.get("reason") or "operator_stop").strip()[:200] or "operator_stop"
        row = self._transition(
            row, STATE_STOP_REQUESTED,
            ts_field="stop_requested_at",
            extra_sets={"stop_reason": reason},
        )
        self._audit(operator["user_id"], "live_session.stop_requested", live_session_id, {
            "session_state": STATE_STOP_REQUESTED,
            "reason": reason,
        })
        row = self._transition(row, STATE_STOPPED, ts_field="stopped_at")
        self._audit(operator["user_id"], "live_session.stopped", live_session_id, {
            "session_state": STATE_STOPPED,
            "reason": reason,
        })
        return self._session_dict(row)

    def mark_failed(self, operator: dict, live_session_id: str, reason: str = "failed") -> dict:
        """Active → FAILED. Used for operator/system failure; no provider calls."""
        self.cp.require_operator(operator)
        self.require_enabled()
        row = self._get_row(live_session_id)
        if not row:
            raise NotFoundError("live session not found", "live_session_not_found")
        if row["session_state"] == STATE_FAILED:
            return self._session_dict(row)
        if row["session_state"] not in _ACTIVE_STATES:
            raise ConflictError(
                f"cannot fail live_session in state {row['session_state']}",
                "illegal_live_session_transition",
            )
        msg = (reason or "failed").strip()[:200] or "failed"
        row = self._transition(
            row, STATE_FAILED,
            ts_field="failed_at",
            extra_sets={"failure_reason": msg},
        )
        self._audit(operator["user_id"], "live_session.failed", live_session_id, {
            "session_state": STATE_FAILED,
            "reason": msg,
        })
        return self._session_dict(row)
