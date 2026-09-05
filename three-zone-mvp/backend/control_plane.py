"""Three-Zone control plane: the single authority for events, rights,
entitlement, lifecycle, playback leases, ingest health, and audit.

The player is never the authority. A viewer receives a short-lived lease only
after :meth:`request_playback` evaluates the current event and rights state, and
the same decision is repeated by :meth:`validate_lease` on every media request.
"""

from __future__ import annotations

import time
import uuid

from . import tokens
from .db import Database, dumps, loads

# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
LIFECYCLE = ["scheduled", "gray", "yellow", "green", "live", "replay", "archive"]
_ALLOWED_TRANSITIONS = {
    "scheduled": {"gray"},
    "gray": {"yellow"},
    "yellow": {"green"},
    "green": {"live"},
    "live": {"replay"},
    "replay": {"archive"},
    "archive": set(),
}

VALID_SOURCES = {"primary", "backup"}


# ---------------------------------------------------------------------------
# Errors -> HTTP status codes
# ---------------------------------------------------------------------------
class ControlError(Exception):
    status = 400

    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.code = code


class AuthError(ControlError):
    status = 401


class ForbiddenError(ControlError):
    status = 403


class NotFoundError(ControlError):
    status = 404


class ConflictError(ControlError):
    status = 409


class ValidationError(ControlError):
    status = 400


def now() -> float:
    return time.time()


class ControlPlane:
    def __init__(self, db: Database, config):
        self.db = db
        self.config = config

    # -- serialisation helpers -------------------------------------------
    @staticmethod
    def _user_dict(row) -> dict:
        return {
            "user_id": row["user_id"],
            "display_name": row["display_name"],
            "role": row["role"],
            "account_state": row["account_state"],
            "subscription": row["subscription"],
            "zones": loads(row["zones"], []),
            "packages": loads(row["packages"], []),
            "destinations": loads(row["destinations"], []),
        }

    def _event_dict(self, row) -> dict:
        rights = self.current_rights(row["event_id"])
        active_source = self._effective_source(row)
        feed_healthy = self._feed_healthy(row, active_source)
        return {
            "event_id": row["event_id"],
            "title": row["title"],
            "zone": row["zone"],
            "category": row["category"],
            "status": row["status"],
            "scheduled_start": row["scheduled_start"],
            "production_mode": row["production_mode"],
            "active_source": active_source,
            "feed_healthy": feed_healthy,
            "primary_last_seen": row["primary_last_seen"],
            "backup_last_seen": row["backup_last_seen"],
            "scoreboard": loads(row["scoreboard"], {}),
            "replay_available": bool(row["replay_available"]),
            "rights": self._rights_public(rights) if rights else None,
        }

    @staticmethod
    def _rights_public(row) -> dict:
        return {
            "version": row["version"],
            "territory": row["territory"],
            "destination": row["destination"],
            "package": row["package"],
            "authority": row["authority"],
            "source_reference": row["source_reference"],
            "active": bool(row["active"]),
            "revoked": bool(row["revoked"]),
            "revocation_reason": row["revocation_reason"],
            "live_window": [row["live_start"], row["live_end"]],
            "replay_window": [row["replay_start"], row["replay_end"]],
            "archive_retention_days": row["archive_retention_days"],
        }

    # -- audit ------------------------------------------------------------
    def audit_log(self, actor: str, action: str, event_id: str | None = None, detail: dict | None = None) -> None:
        self.db.execute(
            "INSERT INTO audit(ts, actor, action, event_id, detail) VALUES (?,?,?,?,?)",
            (now(), actor, action, event_id, dumps(detail or {})),
        )

    def _outbox(self, event_id: str, type_: str, payload: dict) -> None:
        self.db.execute(
            "INSERT INTO socket_outbox(event_id, type, payload, created_at) VALUES (?,?,?,?)",
            (event_id, type_, dumps(payload), now()),
        )

    # -- identity ---------------------------------------------------------
    def get_user(self, user_id: str) -> dict | None:
        row = self.db.query_one("SELECT * FROM users WHERE user_id=?", (user_id,))
        return self._user_dict(row) if row else None

    def demo_login(self, account: str) -> dict:
        if account not in ("demo-viewer", "demo-admin"):
            raise ValidationError("unknown demo account", "unknown_account")
        user = self.get_user(account)
        if not user:
            raise NotFoundError("demo account not provisioned", "unknown_account")
        token = tokens.sign(
            self.config.token_secret, "session", {"sub": account}, self.config.session_ttl
        )
        self.audit_log(account, "auth.demo_login")
        return {"session_token": token, "user": user}

    def verify_session(self, token: str) -> dict:
        try:
            payload = tokens.verify(self.config.token_secret, token, "session")
        except tokens.TokenError as exc:
            raise AuthError(str(exc), "invalid_session") from exc
        user = self.get_user(payload["sub"])
        if not user:
            raise AuthError("session subject unknown", "invalid_session")
        if user["account_state"] != "active":
            raise ForbiddenError("account suspended", "account_suspended")
        return user

    @staticmethod
    def require_operator(user: dict) -> None:
        if user["role"] not in ("operator", "admin"):
            raise ForbiddenError("operator role required", "operator_required")

    # -- rights -----------------------------------------------------------
    def current_rights(self, event_id: str):
        return self.db.query_one(
            "SELECT * FROM rights WHERE event_id=? AND active=1 AND revoked=0"
            " ORDER BY version DESC LIMIT 1",
            (event_id,),
        )

    def _max_version(self, event_id: str) -> int:
        row = self.db.query_one("SELECT MAX(version) AS m FROM rights WHERE event_id=?", (event_id,))
        return int(row["m"]) if row and row["m"] is not None else 0

    # -- events -----------------------------------------------------------
    def get_event_row(self, event_id: str):
        row = self.db.query_one("SELECT * FROM events WHERE event_id=?", (event_id,))
        if not row:
            raise NotFoundError("event not found", "event_not_found")
        return row

    def list_events(self, user: dict) -> list[dict]:
        rows = self.db.query("SELECT * FROM events ORDER BY scheduled_start ASC")
        events = [self._event_dict(r) for r in rows]
        if "*" not in user["zones"]:
            events = [e for e in events if e["zone"] in user["zones"]]
        return events

    def get_event(self, event_id: str, user: dict) -> dict:
        row = self.get_event_row(event_id)
        event = self._event_dict(row)
        if "*" not in user["zones"] and event["zone"] not in user["zones"]:
            raise ForbiddenError("event outside your zone", "zone_not_entitled")
        event["access"] = self.evaluate_access(user, row)["public"]
        return event

    def create_event(self, operator: dict, data: dict) -> dict:
        self.require_operator(operator)
        title = (data.get("title") or "").strip()
        zone = (data.get("zone") or "").strip().lower()
        if not title:
            raise ValidationError("title is required", "title_required")
        if zone not in ("midwest", "west", "east"):
            raise ValidationError("zone must be midwest, west, or east", "bad_zone")
        event_id = "evt_" + uuid.uuid4().hex[:12]
        start = float(data.get("scheduled_start") or now())
        self.db.execute(
            "INSERT INTO events(event_id,title,zone,category,status,scheduled_start,"
            "production_mode,active_source,scoreboard,replay_available,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id, title, zone, (data.get("category") or "general"),
                "scheduled", start, (data.get("production_mode") or "single_camera"),
                "primary", "{}", 0, now(),
            ),
        )
        live_start = start
        live_end = start + 3 * 3600
        self._insert_rights(
            event_id, version=1, territory=zone,
            destination=(data.get("destination") or "web"),
            package=(data.get("package") or "standard"),
            live_window=(live_start, live_end),
            replay_window=(live_start, live_end + 30 * 24 * 3600),
            authority=(data.get("authority") or operator["display_name"]),
            source_reference=(data.get("source_reference") or f"contract://{event_id}"),
        )
        self.audit_log(operator["user_id"], "event.created", event_id, {"title": title, "zone": zone})
        return self._event_dict(self.get_event_row(event_id))

    def _insert_rights(self, event_id, version, territory, destination, package,
                       live_window, replay_window, authority, source_reference,
                       archive_retention_days=365) -> None:
        self.db.execute(
            "INSERT INTO rights(event_id,version,territory,destination,package,live_start,"
            "live_end,replay_start,replay_end,authority,source_reference,active,revoked,"
            "archive_retention_days,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,1,0,?,?)",
            (
                event_id, version, territory, destination, package,
                live_window[0], live_window[1], replay_window[0], replay_window[1],
                authority, source_reference, archive_retention_days, now(),
            ),
        )

    # -- production readiness / heartbeat --------------------------------
    def _feed_healthy(self, event_row, source: str) -> bool:
        last = event_row["primary_last_seen"] if source == "primary" else event_row["backup_last_seen"]
        return last is not None and (now() - last) <= self.config.heartbeat_timeout

    def _effective_source(self, event_row) -> str:
        """Derive the serving source from heartbeat freshness.

        Prefer a fresh primary; fail over to a fresh backup; otherwise keep the
        stored value so the UI can show a stale-but-last-known source.
        """
        p, b = event_row["primary_last_seen"], event_row["backup_last_seen"]
        t = self.config.heartbeat_timeout
        primary_fresh = p is not None and (now() - p) <= t
        backup_fresh = b is not None and (now() - b) <= t
        if primary_fresh:
            return "primary"
        if backup_fresh:
            return "backup"
        return event_row["active_source"]

    def production_ready(self, event_row) -> bool:
        return self._feed_healthy(event_row, self._effective_source(event_row))

    def record_heartbeat(self, event_id: str, token: str, source: str, healthy: bool = True) -> dict:
        try:
            payload = tokens.verify(self.config.token_secret, token, "ingest")
        except tokens.TokenError as exc:
            raise AuthError(str(exc), "invalid_ingest_token") from exc
        if payload.get("event_id") != event_id:
            raise ForbiddenError("ingest token not scoped to this event", "ingest_scope")
        if source not in VALID_SOURCES or payload.get("source") != source:
            raise ForbiddenError("ingest token not scoped to this source", "ingest_scope")
        row = self.get_event_row(event_id)
        prev_source = self._effective_source(row)
        stamp = now() if healthy else None
        col = "primary_last_seen" if source == "primary" else "backup_last_seen"
        if healthy:
            self.db.execute(f"UPDATE events SET {col}=? WHERE event_id=?", (stamp, event_id))
        row = self.get_event_row(event_id)
        new_source = self._effective_source(row)
        if new_source != row["active_source"]:
            self.db.execute("UPDATE events SET active_source=? WHERE event_id=?", (new_source, event_id))
            self.audit_log("system", "feed.failover", event_id,
                           {"from": prev_source, "to": new_source})
        row = self.get_event_row(event_id)
        healthy_now = self._feed_healthy(row, new_source)
        self._outbox(event_id, "feed.heartbeat", {
            "active_source": new_source,
            "feed_healthy": healthy_now,
            "reporting_source": source,
        })
        return {"active_source": new_source, "feed_healthy": healthy_now}

    def issue_ingest_token(self, event_id: str, operator: dict, source: str) -> dict:
        self.require_operator(operator)
        self.get_event_row(event_id)
        if source not in VALID_SOURCES:
            raise ValidationError("source must be primary or backup", "bad_source")
        token = tokens.sign(
            self.config.token_secret, "ingest",
            {"event_id": event_id, "source": source, "jti": uuid.uuid4().hex},
            self.config.ingest_ttl,
        )
        self.audit_log(operator["user_id"], "ingest.token_issued", event_id, {"source": source})
        return {"ingest_token": token, "event_id": event_id, "source": source,
                "expires_in": self.config.ingest_ttl}

    # -- lifecycle --------------------------------------------------------
    def transition(self, event_id: str, operator: dict, target: str) -> dict:
        self.require_operator(operator)
        row = self.get_event_row(event_id)
        current = row["status"]
        if target not in LIFECYCLE:
            raise ValidationError("unknown lifecycle state", "bad_state")
        if target not in _ALLOWED_TRANSITIONS.get(current, set()):
            raise ConflictError(
                f"cannot move from {current} to {target}", "illegal_transition"
            )
        rights = self.current_rights(event_id)
        if target in ("green", "live"):
            if rights is None:
                raise ConflictError("active rights required before clearance", "rights_unavailable")
            if not self.production_ready(row):
                raise ConflictError(
                    "a ready production path (fresh heartbeat) is required", "production_not_ready"
                )
        if target == "yellow" and rights is None:
            raise ConflictError("a rights object is required to begin clearance", "rights_unavailable")
        self.db.execute("UPDATE events SET status=? WHERE event_id=?", (target, event_id))
        if target == "replay":
            self.db.execute("UPDATE events SET replay_available=1 WHERE event_id=?", (event_id,))
        self.audit_log(operator["user_id"], "event.transition", event_id,
                       {"from": current, "to": target})
        self._outbox(event_id, "event.state", {"status": target})
        return self._event_dict(self.get_event_row(event_id))

    def update_score(self, event_id: str, actor: dict, scoreboard: dict) -> dict:
        self.require_operator(actor)
        self.get_event_row(event_id)
        if not isinstance(scoreboard, dict):
            raise ValidationError("scoreboard must be an object", "bad_scoreboard")
        self.db.execute("UPDATE events SET scoreboard=? WHERE event_id=?",
                        (dumps(scoreboard), event_id))
        self.audit_log(actor["user_id"], "event.score", event_id, scoreboard)
        self._outbox(event_id, "score.update", {"scoreboard": scoreboard})
        return self._event_dict(self.get_event_row(event_id))

    def media_end(self, event_id: str, service_key: str) -> dict:
        if not tokens.hmac_equal(service_key, self.config.media_service_key):
            raise ForbiddenError("invalid media service key", "bad_service_key")
        row = self.get_event_row(event_id)
        if row["status"] != "live":
            raise ConflictError("only a live event can end into replay", "not_live")
        self.db.execute("UPDATE events SET status='replay', replay_available=1 WHERE event_id=?",
                        (event_id,))
        self.audit_log("media-service", "event.media_end", event_id, {"from": "live", "to": "replay"})
        self._outbox(event_id, "event.state", {"status": "replay", "reason": "media_end"})
        return self._event_dict(self.get_event_row(event_id))

    # -- rights revoke / restore -----------------------------------------
    def revoke_rights(self, event_id: str, operator: dict, reason: str) -> dict:
        self.require_operator(operator)
        self.get_event_row(event_id)
        rights = self.current_rights(event_id)
        if rights is None:
            raise ConflictError("no active rights to revoke", "rights_unavailable")
        self.db.execute(
            "UPDATE rights SET active=0, revoked=1, revocation_reason=? WHERE id=?",
            (reason or "emergency revocation", rights["id"]),
        )
        self.audit_log(operator["user_id"], "rights.revoked", event_id,
                       {"version": rights["version"], "reason": reason})
        self._outbox(event_id, "rights.revoked", {"version": rights["version"], "reason": reason})
        return self._event_dict(self.get_event_row(event_id))

    def restore_rights(self, event_id: str, operator: dict) -> dict:
        self.require_operator(operator)
        self.get_event_row(event_id)
        prior = self.db.query_one(
            "SELECT * FROM rights WHERE event_id=? ORDER BY version DESC LIMIT 1", (event_id,)
        )
        if prior is None:
            raise ConflictError("no rights history to restore from", "rights_unavailable")
        new_version = self._max_version(event_id) + 1
        self._insert_rights(
            event_id, version=new_version, territory=prior["territory"],
            destination=prior["destination"], package=prior["package"],
            live_window=(prior["live_start"], prior["live_end"]),
            replay_window=(prior["replay_start"], prior["replay_end"]),
            authority=prior["authority"], source_reference=prior["source_reference"],
            archive_retention_days=prior["archive_retention_days"],
        )
        self.audit_log(operator["user_id"], "rights.restored", event_id, {"version": new_version})
        self._outbox(event_id, "rights.restored", {"version": new_version})
        return self._event_dict(self.get_event_row(event_id))

    # -- entitlement & leases --------------------------------------------
    def evaluate_access(self, user: dict, event_row, mode: str | None = None) -> dict:
        """Pure entitlement decision. Returns allow/deny + reason + mode.

        ``public`` is a viewer-safe subset that never leaks why another zone or
        package is gated beyond a coarse reason code.
        """
        def deny(code: str, message: str) -> dict:
            return {"allow": False, "code": code, "message": message, "mode": None,
                    "rights_version": None,
                    "public": {"allow": False, "reason": code}}

        if user["account_state"] != "active":
            return deny("account_suspended", "account is not active")
        if user["subscription"] != "active":
            return deny("subscription_inactive", "subscription is not active")
        zone = event_row["zone"]
        if "*" not in user["zones"] and zone not in user["zones"]:
            return deny("zone_not_entitled", "not entitled in this zone")
        rights = self.current_rights(event_row["event_id"])
        if rights is None:
            return deny("rights_unavailable", "no active rights for this event")
        if "*" not in user["packages"] and rights["package"] not in user["packages"]:
            return deny("package_not_entitled", "package not included in subscription")
        if "*" not in user["destinations"] and rights["destination"] not in user["destinations"]:
            return deny("destination_not_allowed", "destination not permitted")
        status = event_row["status"]
        ts = now()
        if status == "live":
            resolved = "live"
            start, end = rights["live_start"], rights["live_end"]
        elif status == "replay":
            resolved = "replay"
            start, end = rights["replay_start"], rights["replay_end"]
        else:
            return deny("not_playable", f"event is {status}, not playable")
        if mode and mode != resolved:
            return deny("mode_mismatch", f"event is available as {resolved}")
        if start is not None and ts < start:
            return deny("window_not_open", "playback window has not opened")
        if end is not None and ts > end:
            return deny("window_closed", "playback window has closed")
        return {
            "allow": True, "code": "allow", "message": "authorized", "mode": resolved,
            "rights_version": rights["version"],
            "public": {"allow": True, "reason": "authorized", "mode": resolved},
        }

    def request_playback(self, event_id: str, user: dict) -> dict:
        row = self.get_event_row(event_id)
        decision = self.evaluate_access(user, row)
        if not decision["allow"]:
            self.audit_log(user["user_id"], "playback.denied", event_id, {"reason": decision["code"]})
            raise ForbiddenError(decision["message"], decision["code"])
        lease_id = uuid.uuid4().hex
        lease = tokens.sign(
            self.config.token_secret, "lease",
            {
                "sub": user["user_id"], "event_id": event_id,
                "rights_version": decision["rights_version"], "mode": decision["mode"],
                "lease_id": lease_id,
            },
            self.config.lease_ttl,
        )
        self.audit_log(user["user_id"], "playback.granted", event_id,
                       {"mode": decision["mode"], "rights_version": decision["rights_version"]})
        return {
            "allow": True,
            "mode": decision["mode"],
            "rights_version": decision["rights_version"],
            "lease_token": lease,
            "lease_id": lease_id,
            "lease_ttl": self.config.lease_ttl,
            "media_url": f"/demo/media/{event_id}.mp4",
        }

    def validate_lease(self, event_id: str, lease_token: str) -> dict:
        """Re-run authorization for a lease. Called by the media route and by
        the standalone ``/api/leases/validate`` endpoint a media proxy uses."""
        try:
            payload = tokens.verify(self.config.token_secret, lease_token, "lease")
        except tokens.TokenError as exc:
            return {"valid": False, "reason": "invalid_lease", "message": str(exc)}
        if payload.get("event_id") != event_id:
            return {"valid": False, "reason": "event_mismatch", "message": "lease is for another event"}
        user = self.get_user(payload.get("sub", ""))
        if not user:
            return {"valid": False, "reason": "unknown_subject", "message": "lease subject unknown"}
        try:
            row = self.get_event_row(event_id)
        except NotFoundError:
            return {"valid": False, "reason": "event_not_found", "message": "event not found"}
        decision = self.evaluate_access(user, row, mode=payload.get("mode"))
        if not decision["allow"]:
            return {"valid": False, "reason": decision["code"], "message": decision["message"]}
        if decision["rights_version"] != payload.get("rights_version"):
            return {"valid": False, "reason": "rights_version_changed",
                    "message": "rights were revoked or re-versioned"}
        return {"valid": True, "reason": "authorized", "mode": decision["mode"],
                "rights_version": decision["rights_version"], "subject": user["user_id"]}

    # -- analytics & audit ------------------------------------------------
    def analytics(self) -> dict:
        rows = self.db.query("SELECT status, COUNT(*) AS c FROM events GROUP BY status")
        by_status = {r["status"]: r["c"] for r in rows}
        zones = self.db.query("SELECT zone, COUNT(*) AS c FROM events GROUP BY zone")
        by_zone = {r["zone"]: r["c"] for r in zones}
        metrics = self.db.query_one("SELECT * FROM socket_metrics WHERE id=1")
        socket_fresh = metrics is not None and (now() - metrics["updated_at"]) <= 10
        return {
            "events_total": sum(by_status.values()),
            "events_by_status": by_status,
            "events_by_zone": by_zone,
            "socket_connections": metrics["connections"] if metrics else 0,
            "socket_per_event": loads(metrics["per_event"], {}) if metrics else {},
            "socket_metrics_fresh": bool(socket_fresh),
        }

    def audit_view(self, operator: dict, limit: int = 200) -> list[dict]:
        self.require_operator(operator)
        rows = self.db.query("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
        return [
            {"id": r["id"], "ts": r["ts"], "actor": r["actor"], "action": r["action"],
             "event_id": r["event_id"], "detail": loads(r["detail"], {})}
            for r in rows
        ]
