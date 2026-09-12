"""L1B / L1B+ — operator-only private live capture sessions + private ingest.

Lifecycle (server-enforced):
  REQUESTED → CAPTURE_STARTING → VERIFYING_PRIVATE → STOP_REQUESTED → STOPPED
  REQUESTED | CAPTURE_STARTING | VERIFYING_PRIVATE → FAILED

Server-forced truth on create (clients cannot override):
  public_state=LIVE_PRIVATE
  distribution_state=DISABLED
  sports_status=UNVERIFIED
  safety_state=NOT_EVALUATED
  provider_name=local_browser (no Restream / Cloudflare live input)

L1B+ / G4-A — private server-side ingest bound to an active live_session:
  NONE → BOUND → RECEIVING → CLOSED
  Media/handle stays private; distribution remains DISABLED; no public live input.

Does NOT call media_provider, restream, AI, xrpl, settlement, Moten intake,
or ControlPlane.transition(live). Audits via ControlPlane.audit_log only
(no Moten outbox handoff for these events).
"""

from __future__ import annotations

import base64
import hashlib
import os
import uuid
from pathlib import Path
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

# L1B+ private ingest states (server-assigned only).
INGEST_NONE = "NONE"
INGEST_BOUND = "BOUND"
INGEST_RECEIVING = "RECEIVING"
INGEST_CLOSED = "CLOSED"

# Soft cap for private media body in one request (bytes). Keeps L1B+ small.
_MAX_PRIVATE_MEDIA_BYTES = 256 * 1024

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
    "private_ingest_id",
    "private_ingest_state",
    "private_ingest_bound_at",
    "private_ingest_closed_at",
    "private_ingest_byte_count",
    "publication",
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

_INGEST_ACTIVE = frozenset({INGEST_BOUND, INGEST_RECEIVING})


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


def _row_get(row, key: str, default=None):
    try:
        val = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if val is None and default is not None else val


class LiveSessionService:
    """Private live_session lifecycle — operator/owner only."""

    def __init__(self, cp: ControlPlane, media_dir: str | None = None):
        self.cp = cp
        self.db = cp.db
        self.media_dir = media_dir or "data/media"

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
    def _private_ingest_block(self, r: dict[str, Any]) -> dict[str, Any]:
        state = r.get("private_ingest_state") or INGEST_NONE
        bound = bool(r.get("private_ingest_id")) and state in _INGEST_ACTIVE
        return {
            "private_ingest_id": r.get("private_ingest_id"),
            "private_ingest_state": state,
            "private_ingest_bound_at": r.get("private_ingest_bound_at"),
            "private_ingest_closed_at": r.get("private_ingest_closed_at"),
            "private_ingest_byte_count": int(r.get("private_ingest_byte_count") or 0),
            "published": False,
            "distribution_state": DISTRIBUTION_DISABLED,
            "label": (
                "Private ingest bound — not published"
                if bound or state == INGEST_RECEIVING
                else (
                    "Private ingest closed — not published"
                    if state == INGEST_CLOSED
                    else "No private ingest — Browser source not published"
                )
            ),
        }

    def _session_dict(self, row) -> dict[str, Any]:
        r = _row_dict(row)
        ingest = self._private_ingest_block(r)
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
            "private_ingest": ingest,
            # Honest operator label — never implies publication.
            "publication": {
                "browser_source_published": False,
                "distribution_state": r["distribution_state"],
                "private_ingest_state": ingest["private_ingest_state"],
                "label": (
                    "Private capture session — Private ingest bound — not published"
                    if ingest["private_ingest_state"] in (INGEST_BOUND, INGEST_RECEIVING)
                    else "Private capture session — Browser source not published"
                ),
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

    def _private_dir(self, live_session_id: str) -> Path:
        root = Path(self.media_dir) / "private_ingest" / live_session_id
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _close_ingest_if_open(self, row) -> Any:
        state = _row_get(row, "private_ingest_state") or INGEST_NONE
        if state not in _INGEST_ACTIVE:
            return row
        ts = now()
        self.db.execute(
            "UPDATE live_sessions SET private_ingest_state=?, "
            "private_ingest_closed_at=?, updated_at=? WHERE live_session_id=?",
            (INGEST_CLOSED, ts, ts, row["live_session_id"]),
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
            "stopped_at, failed_at, "
            "private_ingest_id, private_ingest_state, private_ingest_bound_at, "
            "private_ingest_closed_at, private_ingest_byte_count, "
            "created_at, updated_at"
            ") VALUES ("
            "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?"
            ")",
            (
                sid, actor_id, event_id, property_id, team_id,
                STATE_REQUESTED, SPORTS_UNVERIFIED, None, PUBLIC_STATE_LIVE_PRIVATE,
                DISTRIBUTION_DISABLED, SAFETY_NOT_EVALUATED, rights_version, POLICY_VERSION,
                None, None, PROVIDER_NAME, None,
                None, None, None, supersedes,
                idem, fp, env, ts,
                None, None, None,
                None, None,
                None, INGEST_NONE, None,
                None, 0,
                ts, ts,
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

    def bind_private_ingest(self, operator: dict, live_session_id: str,
                            data: dict | None = None) -> dict:
        """L1B+: bind a private server-side ingest handle to an active session.

        Does not call media_provider / Cloudflare live input / Restream.
        Forces distribution_state=DISABLED and public_state=LIVE_PRIVATE.
        """
        self.cp.require_operator(operator)
        self.require_enabled()
        # Strip any client attempts to force public / restream truth.
        self.strip_client_payload(data)
        row = self._get_row(live_session_id)
        if not row:
            raise NotFoundError("live session not found", "live_session_not_found")
        if row["session_state"] != STATE_VERIFYING_PRIVATE:
            raise ConflictError(
                f"private ingest requires VERIFYING_PRIVATE (got {row['session_state']})",
                "illegal_private_ingest_state",
            )
        # Re-force truth even if a client somehow mutated (defense in depth).
        if row["public_state"] != PUBLIC_STATE_LIVE_PRIVATE or row["distribution_state"] != DISTRIBUTION_DISABLED:
            self.db.execute(
                "UPDATE live_sessions SET public_state=?, distribution_state=?, "
                "updated_at=? WHERE live_session_id=?",
                (PUBLIC_STATE_LIVE_PRIVATE, DISTRIBUTION_DISABLED, now(), live_session_id),
            )
            row = self._get_row(live_session_id)

        existing_state = _row_get(row, "private_ingest_state") or INGEST_NONE
        existing_id = _row_get(row, "private_ingest_id")
        if existing_id and existing_state in _INGEST_ACTIVE:
            # Idempotent re-bind of the same active handle.
            return self._session_dict(row)
        if existing_state == INGEST_CLOSED:
            raise ConflictError(
                "private ingest already closed for this session",
                "private_ingest_closed",
            )

        pid = "pi_" + uuid.uuid4().hex[:16]
        ts = now()
        # Ensure private directory exists (handle-only; no public URL).
        self._private_dir(live_session_id)
        self.db.execute(
            "UPDATE live_sessions SET private_ingest_id=?, private_ingest_state=?, "
            "private_ingest_bound_at=?, provider_name=?, provider_stream_id=?, "
            "restream_event_id=?, public_state=?, distribution_state=?, "
            "updated_at=? WHERE live_session_id=?",
            (
                pid, INGEST_BOUND, ts,
                PROVIDER_NAME, None,  # never a Cloudflare/Restream public id
                None,
                PUBLIC_STATE_LIVE_PRIVATE, DISTRIBUTION_DISABLED,
                ts, live_session_id,
            ),
        )
        row = self._get_row(live_session_id)
        self._audit(operator["user_id"], "live_session.private_ingest_bound", live_session_id, {
            "private_ingest_id": pid,
            "private_ingest_state": INGEST_BOUND,
            "public_state": PUBLIC_STATE_LIVE_PRIVATE,
            "distribution_state": DISTRIBUTION_DISABLED,
            "published": False,
        })
        return self._session_dict(row)

    def receive_private_media(self, operator: dict, live_session_id: str,
                              data: dict | None = None) -> dict:
        """L1B+: accept a small private media blob for a bound ingest.

        Stores bytes under media_dir/private_ingest/<session>/ only.
        Never provisions Cloudflare public live input or Restream.
        """
        self.cp.require_operator(operator)
        self.require_enabled()
        payload = self.strip_client_payload(data)
        row = self._get_row(live_session_id)
        if not row:
            raise NotFoundError("live session not found", "live_session_not_found")
        if row["session_state"] != STATE_VERIFYING_PRIVATE:
            raise ConflictError(
                f"private media requires VERIFYING_PRIVATE (got {row['session_state']})",
                "illegal_private_ingest_state",
            )
        ingest_state = _row_get(row, "private_ingest_state") or INGEST_NONE
        if ingest_state not in _INGEST_ACTIVE:
            raise ConflictError(
                "private ingest not bound",
                "private_ingest_not_bound",
            )

        raw_b64 = payload.get("content_base64")
        if raw_b64 is None:
            raise ValidationError("content_base64 required", "missing_content")
        if not isinstance(raw_b64, str):
            raise ValidationError("content_base64 must be a string", "bad_content")
        try:
            blob = base64.b64decode(raw_b64, validate=True)
        except Exception as exc:
            raise ValidationError("invalid content_base64", "bad_content") from exc
        if len(blob) == 0:
            raise ValidationError("empty content", "bad_content")
        if len(blob) > _MAX_PRIVATE_MEDIA_BYTES:
            raise ValidationError(
                f"content exceeds {_MAX_PRIVATE_MEDIA_BYTES} bytes",
                "content_too_large",
            )

        asset_id = "priv_asset_" + uuid.uuid4().hex[:16]
        digest = hashlib.sha256(blob).hexdigest()
        dest = self._private_dir(live_session_id) / f"{asset_id}.bin"
        dest.write_bytes(blob)
        # Restrictive perms when supported (best-effort on all platforms).
        try:
            os.chmod(dest, 0o600)
        except OSError:
            pass

        prev = int(_row_get(row, "private_ingest_byte_count") or 0)
        ts = now()
        self.db.execute(
            "UPDATE live_sessions SET private_ingest_state=?, source_asset_id=?, "
            "source_hash=?, private_ingest_byte_count=?, public_state=?, "
            "distribution_state=?, provider_name=?, provider_stream_id=?, "
            "restream_event_id=?, updated_at=? WHERE live_session_id=?",
            (
                INGEST_RECEIVING, asset_id, digest, prev + len(blob),
                PUBLIC_STATE_LIVE_PRIVATE, DISTRIBUTION_DISABLED,
                PROVIDER_NAME, None, None,
                ts, live_session_id,
            ),
        )
        row = self._get_row(live_session_id)
        self._audit(operator["user_id"], "live_session.private_ingest_media", live_session_id, {
            "private_ingest_id": row["private_ingest_id"],
            "private_ingest_state": INGEST_RECEIVING,
            "source_asset_id": asset_id,
            "source_hash": digest,
            "bytes": len(blob),
            "published": False,
            "distribution_state": DISTRIBUTION_DISABLED,
        })
        return self._session_dict(row)

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
                row = self._close_ingest_if_open(row)
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
        row = self._close_ingest_if_open(row)
        if (_row_get(row, "private_ingest_state") or INGEST_NONE) == INGEST_CLOSED:
            self._audit(operator["user_id"], "live_session.private_ingest_closed", live_session_id, {
                "private_ingest_id": _row_get(row, "private_ingest_id"),
                "private_ingest_state": INGEST_CLOSED,
                "published": False,
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
        row = self._close_ingest_if_open(row)
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
