"""Hosted media rail: provision, webhooks, viewer sessions, settlement.

A signed HLS URL may remain playable until its token expires and already-
buffered segments may drain. Immediate segment-level kill requires a later
edge Worker; this module does not treat the manifest URL as an instant switch.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import uuid

from . import tokens
from .db import dumps, loads
from .merkle import hash_canonical, merkle_proof, merkle_root, verify_proof
from .xrpl_adapter import XrplAdapter


def _now() -> float:
    from .control_plane import now
    return now()


class PipelineMixin:
    """Methods mixed into ControlPlane. ``self`` is a ControlPlane instance."""

    def _canonical_audit(self, event_type: str, subject_id=None, actor_type="system",
                         actor_id="system", payload=None, rights_version=None) -> None:
        payload = dict(payload or {})
        blob = json.dumps(payload).lower()
        for needle in ("stream_key", "streamkey", "signing_secret", "api_token",
                       "authorization", "lease_token"):
            if needle in blob:
                raise RuntimeError("refusing to audit a payload that contains a secret field")
        from .portal import PortalService
        PortalService(self).audit(
            event_type, subject_id, actor_type, actor_id, payload,
            rights_version=rights_version,
        )

    def _event_map(self, row) -> dict:
        return {k: row[k] for k in row.keys()}

    def _pseudonym(self, user_id: str) -> str:
        return hmac.new(
            self.config.token_secret.encode("utf-8"),
            user_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _persist_lease(self, lease_id: str, event_id: str, user_id: str,
                       rights_version: int, mode: str, ttl: int) -> None:
        stamp = _now()
        self.db.execute(
            "INSERT OR REPLACE INTO lease_records(lease_id,event_id,member_id,session_id,"
            "rights_version,permitted_use,status,issued_at,hard_expiry,close_reason)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (lease_id, event_id, user_id, "cp", rights_version, mode, "active",
             stamp, stamp + ttl, None),
        )

    def can_audit_property(self, user: dict, property_id: str) -> bool:
        if user["role"] in ("operator", "owner", "admin"):
            return True
        if user["role"] == "auditor":
            return property_id in (user.get("properties") or [])
        return False

    def require_property_auditor(self, user: dict, property_id: str) -> None:
        from .control_plane import ForbiddenError
        if not self.can_audit_property(user, property_id):
            raise ForbiddenError("property audit not permitted", "property_forbidden")

    # -- provision / rotate / status / sync --------------------------------
    def provision_media(self, event_id: str, operator: dict) -> dict:
        from .control_plane import ConflictError
        self.require_operator(operator)
        row = self.get_event_row(event_id)
        if row["provider_input_id"]:
            raise ConflictError("this event already has a live input", "already_provisioned")
        event = self._event_map(row)
        result = self.provider.provision(event)
        self.db.execute(
            "UPDATE events SET media_provider=?, provider_input_id=?, provider_state=? "
            "WHERE event_id=?",
            (self.provider.name, result.input_id, result.state, event_id),
        )
        self._canonical_audit(
            "MEDIA_INPUT_PROVISIONED", event_id, "operator", operator["user_id"],
            {"input_id": result.input_id, "provider": self.provider.name,
             "recording": result.recording_policy},
        )
        # Stream key returned once and never stored.
        return {
            "event_id": event_id,
            "input_id": result.input_id,
            "ingest_url": result.ingest_url,
            "stream_key": result.stream_key,
            "provider": self.provider.name,
            "state": result.state,
        }

    def rotate_media_key(self, event_id: str, operator: dict) -> dict:
        from .control_plane import ConflictError
        self.require_operator(operator)
        row = self.get_event_row(event_id)
        if not row["provider_input_id"]:
            raise ConflictError("event has no live input", "not_provisioned")
        result = self.provider.rotate_key(self._event_map(row))
        self.db.execute(
            "UPDATE events SET provider_state=? WHERE event_id=?",
            (result.state, event_id),
        )
        self._canonical_audit(
            "MEDIA_INPUT_KEY_ROTATED", event_id, "operator", operator["user_id"],
            {"input_id": result.input_id, "provider": self.provider.name},
        )
        return {
            "event_id": event_id,
            "input_id": result.input_id,
            "ingest_url": result.ingest_url,
            "stream_key": result.stream_key,
            "provider": self.provider.name,
        }

    def media_status(self, event_id: str, operator: dict) -> dict:
        self.require_operator(operator)
        row = self.get_event_row(event_id)
        status = self.provider.status(self._event_map(row))
        self._canonical_audit(
            "MEDIA_PROVIDER_STATUS", event_id, "operator", operator["user_id"],
            {"state": status.state, "recording_state": status.recording_state},
        )
        return {
            "event_id": event_id,
            "provider": self.provider.name,
            "provider_state": row["provider_state"],
            "input_id": row["provider_input_id"],
            "video_id": row["provider_video_id"],
            "replay_video_id": row["provider_replay_video_id"],
            "replay_pending": bool(row["replay_pending"]),
            "replay_available": bool(row["replay_available"]),
            "status": status.state,
            "recording_state": status.recording_state,
            "connected": status.connected,
            "error": status.error,
        }

    def sync_media(self, event_id: str, operator: dict) -> dict:
        self.require_operator(operator)
        row = self.get_event_row(event_id)
        status = self.provider.status(self._event_map(row))
        replay_id = status.replay_video_id
        video_id = status.active_video_id
        pending = row["replay_pending"]
        available = row["replay_available"]
        if replay_id and pending:
            pending = 0
            available = 1
        updates = {
            "provider_state": status.state,
            "provider_video_id": video_id or row["provider_video_id"],
            "provider_replay_video_id": replay_id or row["provider_replay_video_id"],
            "replay_pending": pending,
            "replay_available": available,
        }
        self.db.execute(
            "UPDATE events SET provider_state=?, provider_video_id=?, provider_replay_video_id=?,"
            " replay_pending=?, replay_available=? WHERE event_id=?",
            (updates["provider_state"], updates["provider_video_id"],
             updates["provider_replay_video_id"], updates["replay_pending"],
             updates["replay_available"], event_id),
        )
        self.snapshot_analytics(event_id)
        self._canonical_audit(
            "MEDIA_PROVIDER_STATUS", event_id, "operator", operator["user_id"],
            {"state": status.state, "replay_pending": bool(pending),
             "replay_available": bool(available)},
        )
        return self.media_status(event_id, operator)

    # -- webhook -----------------------------------------------------------
    def handle_provider_webhook(self, payload: dict, secret: str) -> dict:
        from .control_plane import AuthError
        expected = self.config.cf_webhook_secret or ""
        if not expected or not tokens.hmac_equal(secret or "", expected):
            raise AuthError("invalid webhook secret", "bad_webhook_secret")
        parsed = self.provider.parse_webhook(payload or {})
        stamp = _now()
        try:
            self.db.execute(
                "INSERT INTO webhook_inbox(input_id,event_type,ts,received_at) VALUES (?,?,?,?)",
                (parsed.input_id, parsed.event_type, parsed.timestamp, stamp),
            )
        except sqlite3.IntegrityError:
            return {"ok": True, "duplicate": True}

        row = self.db.query_one(
            "SELECT * FROM events WHERE provider_input_id=?", (parsed.input_id,)
        )
        if not row:
            self._canonical_audit(
                "MEDIA_PROVIDER_STATUS", None, "service", "webhook",
                {"ignored": True, "reason": "unknown_input", "event_type": parsed.event_type},
            )
            return {"ok": True, "ignored": True, "reason": "unknown_input"}

        event_id = row["event_id"]
        event_type = (parsed.event_type or "").lower()
        provider_error = parsed.error
        new_state = row["provider_state"]
        video_id = parsed.video_id or row["provider_video_id"]
        replay_id = row["provider_replay_video_id"]
        pending = row["replay_pending"]
        available = row["replay_available"]
        status = row["status"]

        connected = event_type in ("connected", "live_input.connected", "stream.live", "live")
        disconnected = event_type in ("disconnected", "live_input.disconnected", "stream.disconnected")
        errored = event_type in ("errored", "error", "failed") or bool(provider_error)
        ready = event_type in ("ready", "video.ready", "vod.ready")

        if connected:
            new_state = "connected"
            self.db.execute(
                "UPDATE events SET primary_last_seen=? WHERE event_id=?", (stamp, event_id)
            )
            rights = self.current_rights(event_id)
            row = self.get_event_row(event_id)
            status = row["status"]
            if rights and status == "green":
                self.db.execute("UPDATE events SET status='live' WHERE event_id=?", (event_id,))
                self._canonical_audit("EVENT_STARTED", event_id, "service", "webhook",
                                      {"via": "provider_connected"})
                self._outbox(event_id, "event.state", {"status": "live", "reason": "provider_connected"})
            elif status == "live":
                pass  # stay live
            # yellow / gray / scheduled / replay never auto-start
        elif disconnected:
            new_state = "disconnected"
        elif errored:
            new_state = "errored"
        elif ready and parsed.video_id:
            replay_id = parsed.video_id
            if pending:
                pending = 0
                available = 1

        self.db.execute(
            "UPDATE events SET provider_state=?, provider_last_webhook_at=?, provider_last_error=?,"
            " provider_video_id=?, provider_replay_video_id=?, replay_pending=?, replay_available=?"
            " WHERE event_id=?",
            (new_state, stamp, provider_error, video_id, replay_id, pending, available, event_id),
        )
        self._canonical_audit(
            "MEDIA_PROVIDER_STATUS", event_id, "service", "webhook",
            {"event_type": parsed.event_type, "provider_state": new_state},
        )
        return {"ok": True, "event_id": event_id, "provider_state": new_state}

    # -- view sessions -----------------------------------------------------
    def close_stale_view_sessions(self, event_id: str | None = None) -> int:
        cutoff = _now() - self.config.viewer_stale_after
        if event_id:
            rows = self.db.query(
                "SELECT * FROM view_sessions WHERE event_id=? AND state='open'", (event_id,)
            )
        else:
            rows = self.db.query("SELECT * FROM view_sessions WHERE state='open'")
        closed = 0
        for row in rows:
            last = row["last_heartbeat_at"] or row["started_at"]
            if last < cutoff:
                self._finalize_view_session(dict(row), "stale")
                closed += 1
        return closed

    def start_view_session(self, event_id: str, user: dict, lease_id: str) -> dict:
        from .control_plane import ForbiddenError, ValidationError
        if not lease_id:
            raise ValidationError("lease_id is required", "lease_required")
        row = self.get_event_row(event_id)
        decision = self.evaluate_access(user, row)
        if not decision["allow"]:
            raise ForbiddenError(decision["message"], decision["code"])
        lease = self.db.query_one(
            "SELECT * FROM lease_records WHERE lease_id=? AND event_id=? AND member_id=?",
            (lease_id, event_id, user["user_id"]),
        )
        if not lease or lease["status"] != "active" or lease["hard_expiry"] < _now():
            raise ForbiddenError("current lease is required", "invalid_lease")
        existing = self.db.query_one(
            "SELECT * FROM view_sessions WHERE event_id=? AND user_id=? AND state='open'",
            (event_id, user["user_id"]),
        )
        if existing:
            return self._view_session_public(existing)
        rights = self.current_rights(event_id)
        session_id = "VS-" + uuid.uuid4().hex
        stamp = _now()
        self.db.execute(
            "INSERT INTO view_sessions(session_id,event_id,user_id,pseudonym,lease_id,rights_id,"
            "rights_version,started_at,ended_at,last_seq,last_heartbeat_at,qualified_seconds,"
            "state,close_reason,digest,canonical_json,property_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (session_id, event_id, user["user_id"], self._pseudonym(user["user_id"]),
             lease_id, rights["id"] if rights else None, decision["rights_version"],
             stamp, None, 0, stamp, 0, "open", None, None, None, row["property_id"]),
        )
        self._canonical_audit(
            "VIEW_SESSION_STARTED", session_id, "member", "viewer",
            {"event_id": event_id, "lease_id": lease_id,
             "rights_version": decision["rights_version"]},
            rights_version=decision["rights_version"],
        )
        return self._view_session_public(
            self.db.query_one("SELECT * FROM view_sessions WHERE session_id=?", (session_id,))
        )

    def view_heartbeat(self, session_id: str, user: dict, body: dict) -> dict:
        from .control_plane import ForbiddenError, NotFoundError, ValidationError
        self.close_stale_view_sessions()
        row = self.db.query_one("SELECT * FROM view_sessions WHERE session_id=?", (session_id,))
        if not row:
            raise NotFoundError("view session not found", "session_not_found")
        if row["user_id"] != user["user_id"]:
            raise ForbiddenError("session belongs to another viewer", "session_forbidden")
        if row["state"] != "open":
            raise ForbiddenError("view session is closed", "session_closed")
        seq = int(body.get("seq") or 0)
        if seq <= 0:
            raise ValidationError("seq must be a positive integer", "bad_seq")
        existing = self.db.query_one(
            "SELECT * FROM viewing_heartbeats WHERE session_id=? AND seq=?",
            (session_id, seq),
        )
        if existing:
            return {
                "session_id": session_id,
                "seq": seq,
                "credited_seconds": existing["credited_seconds"],
                "qualified_seconds": row["qualified_seconds"],
                "duplicate": True,
            }
        event_row = self.get_event_row(row["event_id"])
        decision = self.evaluate_access(user, event_row)
        if not decision["allow"]:
            reason = "rights_revoked" if decision["code"] in (
                "rights_unavailable", "rights_version_changed"
            ) else "access_denied"
            self._finalize_view_session(dict(row), reason)
            raise ForbiddenError(decision["message"], decision["code"])
        if decision["rights_version"] != row["rights_version"]:
            self._finalize_view_session(dict(row), "rights_revoked")
            raise ForbiddenError("rights were re-versioned", "rights_version_changed")

        playing = bool(body.get("playing"))
        page_visible = bool(body.get("page_visible"))
        position = body.get("position_seconds")
        stamp = _now()
        last = row["last_heartbeat_at"] or row["started_at"]
        delta = max(0.0, stamp - last)
        cap = self.config.viewer_heartbeat_interval * 1.5
        credited = min(delta, cap) if playing and page_visible else 0.0
        self.db.execute(
            "INSERT INTO viewing_heartbeats(session_id,seq,playing,page_visible,position_seconds,"
            "credited_seconds,ts) VALUES (?,?,?,?,?,?,?)",
            (session_id, seq, 1 if playing else 0, 1 if page_visible else 0,
             position, credited, stamp),
        )
        new_total = float(row["qualified_seconds"]) + credited
        new_last_seq = max(int(row["last_seq"] or 0), seq)
        self.db.execute(
            "UPDATE view_sessions SET last_seq=?, last_heartbeat_at=?, qualified_seconds=? "
            "WHERE session_id=?",
            (new_last_seq, stamp, new_total, session_id),
        )
        return {
            "session_id": session_id,
            "seq": seq,
            "credited_seconds": credited,
            "qualified_seconds": new_total,
        }

    def end_view_session(self, session_id: str, user: dict, reason: str = "pagehide") -> dict:
        from .control_plane import ForbiddenError, NotFoundError
        row = self.db.query_one("SELECT * FROM view_sessions WHERE session_id=?", (session_id,))
        if not row:
            raise NotFoundError("view session not found", "session_not_found")
        if row["user_id"] != user["user_id"] and user.get("role") not in ("operator", "owner", "admin"):
            raise ForbiddenError("session belongs to another viewer", "session_forbidden")
        if row["state"] != "open":
            return self._view_session_public(row)
        closed = self._finalize_view_session(dict(row), reason or "pagehide")
        return self._view_session_public(closed)

    def _finalize_view_session(self, row: dict, reason: str):
        stamp = _now()
        canonical = {
            "session_id": row["session_id"],
            "event_id": row["event_id"],
            "property_id": row["property_id"],
            "pseudonym": row["pseudonym"],
            "lease_id": row["lease_id"],
            "rights_version": row["rights_version"],
            "started_at": round(float(row["started_at"]), 3),
            "ended_at": round(stamp, 3),
            "qualified_seconds": round(float(row["qualified_seconds"] or 0), 3),
            "close_reason": reason,
            "state": "closed",
        }
        digest = hash_canonical(canonical)
        blob = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
        self.db.execute(
            "UPDATE view_sessions SET state='closed', close_reason=?, ended_at=?, digest=?,"
            " canonical_json=? WHERE session_id=?",
            (reason, stamp, digest, blob, row["session_id"]),
        )
        self._canonical_audit(
            "VIEW_SESSION_ENDED", row["session_id"], "system", "viewer",
            {"event_id": row["event_id"], "close_reason": reason, "digest": digest},
        )
        return self.db.query_one(
            "SELECT * FROM view_sessions WHERE session_id=?", (row["session_id"],)
        )

    def _close_open_sessions_for_event(self, event_id: str, reason: str) -> None:
        rows = self.db.query(
            "SELECT * FROM view_sessions WHERE event_id=? AND state='open'", (event_id,)
        )
        for row in rows:
            self._finalize_view_session(dict(row), reason)

    @staticmethod
    def _view_session_public(row) -> dict:
        return {
            "session_id": row["session_id"],
            "event_id": row["event_id"],
            "pseudonym": row["pseudonym"],
            "lease_id": row["lease_id"],
            "rights_version": row["rights_version"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "qualified_seconds": row["qualified_seconds"],
            "state": row["state"],
            "close_reason": row["close_reason"],
            "digest": row["digest"],
        }

    # -- settlement + property audit ---------------------------------------
    def settlement_manifest(self, event_id: str, operator: dict) -> dict:
        self.require_operator(operator)
        row = self.get_event_row(event_id)
        self.close_stale_view_sessions(event_id)
        sessions = [
            dict(r) for r in self.db.query(
                "SELECT * FROM view_sessions WHERE event_id=? AND state='closed' "
                "AND digest IS NOT NULL ORDER BY session_id ASC",
                (event_id,),
            )
        ]
        leaves = [s["digest"] for s in sessions]
        root = merkle_root(leaves)
        property_id = row["property_id"] or "unassigned"
        qualified = round(sum(float(s["qualified_seconds"] or 0) for s in sessions), 3)
        stamp = _now()
        settlement_id = "SET-" + uuid.uuid4().hex[:16]
        manifest = {
            "settlement_id": settlement_id,
            "property_id": property_id,
            "event_id": event_id,
            "period_start": min((s["started_at"] for s in sessions), default=None),
            "period_end": max((s["ended_at"] or 0 for s in sessions), default=None),
            "session_count": len(sessions),
            "qualified_seconds": qualified,
            "merkle_root": root,
            "sessions": [
                {
                    "session_id": s["session_id"],
                    "pseudonym": s["pseudonym"],
                    "digest": s["digest"],
                    "qualified_seconds": s["qualified_seconds"],
                }
                for s in sessions
            ],
        }
        manifest_digest = hash_canonical({
            "settlement_id": settlement_id,
            "property_id": property_id,
            "event_id": event_id,
            "session_count": len(sessions),
            "qualified_seconds": qualified,
            "merkle_root": root,
            "session_digests": leaves,
        })
        manifest["manifest_digest"] = manifest_digest
        self.db.execute(
            "INSERT INTO settlements(settlement_id,property_id,event_id,period_start,period_end,"
            "session_count,qualified_seconds,manifest_json,manifest_digest,merkle_root,status,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (settlement_id, property_id, event_id, manifest["period_start"], manifest["period_end"],
             len(sessions), qualified, dumps(manifest), manifest_digest, root, "generated", stamp),
        )
        for index, session in enumerate(sessions):
            proof = merkle_proof(leaves, index)
            self.db.execute(
                "INSERT INTO settlement_leaves(settlement_id,leaf_index,session_id,digest,proof_json)"
                " VALUES (?,?,?,?,?)",
                (settlement_id, index, session["session_id"], session["digest"], dumps(proof)),
            )
        publication = self.xrpl.publish(self.db, {
            "settlement_id": settlement_id,
            "manifest_digest": manifest_digest,
            "merkle_root": root,
            "session_count": len(sessions),
            "qualified_seconds": qualified,
            "property_id": property_id,
            "event_id": event_id,
        })
        self._canonical_audit(
            "SETTLEMENT_MANIFEST_GENERATED", settlement_id, "operator", operator["user_id"],
            {"event_id": event_id, "manifest_digest": manifest_digest, "merkle_root": root,
             "session_count": len(sessions)},
        )
        self._canonical_audit(
            "XRPL_PUBLICATION_QUEUED", settlement_id, "system", "xrpl-adapter",
            {"status": publication["status"], "simulated": bool(publication["simulated"]),
             "tx_hash": publication["tx_hash"]},
        )
        manifest["publication"] = {
            "status": publication["status"],
            "simulated": bool(publication["simulated"]),
            "tx_hash": publication["tx_hash"],
        }
        return manifest

    def list_property_settlements(self, property_id: str, user: dict) -> list[dict]:
        self.require_property_auditor(user, property_id)
        rows = self.db.query(
            "SELECT * FROM settlements WHERE property_id=? ORDER BY created_at DESC",
            (property_id,),
        )
        return [self._settlement_public(r) for r in rows]

    def get_property_settlement(self, property_id: str, settlement_id: str, user: dict) -> dict:
        self.require_property_auditor(user, property_id)
        row = self._settlement_row(property_id, settlement_id)
        payload = self._settlement_public(row)
        payload["manifest"] = loads(row["manifest_json"], {})
        return payload

    def list_settlement_sessions(self, property_id: str, settlement_id: str, user: dict) -> list[dict]:
        self.require_property_auditor(user, property_id)
        self._settlement_row(property_id, settlement_id)
        leaves = self.db.query(
            "SELECT * FROM settlement_leaves WHERE settlement_id=? ORDER BY leaf_index ASC",
            (settlement_id,),
        )
        out = []
        for leaf in leaves:
            session = self.db.query_one(
                "SELECT session_id,pseudonym,qualified_seconds,digest,close_reason "
                "FROM view_sessions WHERE session_id=?",
                (leaf["session_id"],),
            )
            out.append({
                "session_id": leaf["session_id"],
                "pseudonym": session["pseudonym"] if session else None,
                "digest": leaf["digest"],
                "qualified_seconds": session["qualified_seconds"] if session else None,
                "close_reason": session["close_reason"] if session else None,
            })
        return out

    def settlement_session_proof(self, property_id: str, settlement_id: str,
                                 session_id: str, user: dict) -> dict:
        self.require_property_auditor(user, property_id)
        settlement = self._settlement_row(property_id, settlement_id)
        leaf = self.db.query_one(
            "SELECT * FROM settlement_leaves WHERE settlement_id=? AND session_id=?",
            (settlement_id, session_id),
        )
        from .control_plane import NotFoundError
        if not leaf:
            raise NotFoundError("session not in this settlement", "leaf_not_found")
        proof = loads(leaf["proof_json"], [])
        ok = verify_proof(leaf["digest"], proof, settlement["merkle_root"])
        self._canonical_audit(
            "SETTLEMENT_PROOF_ISSUED", session_id, "operator", user["user_id"],
            {"settlement_id": settlement_id, "included": ok},
        )
        return {
            "session_id": session_id,
            "digest": leaf["digest"],
            "merkle_root": settlement["merkle_root"],
            "proof": proof,
            "included": ok,
        }

    def verify_property_settlement(self, property_id: str, settlement_id: str, user: dict) -> dict:
        self.require_property_auditor(user, property_id)
        settlement = self._settlement_row(property_id, settlement_id)
        leaves = [
            dict(r) for r in self.db.query(
                "SELECT * FROM settlement_leaves WHERE settlement_id=? ORDER BY leaf_index ASC",
                (settlement_id,),
            )
        ]
        pub = self.db.query_one(
            "SELECT * FROM xrpl_publication_queue WHERE settlement_id=? "
            "ORDER BY created_at DESC LIMIT 1",
            (settlement_id,),
        )
        expected = settlement["session_count"]
        if len(leaves) != expected:
            result = "INCOMPLETE"
        else:
            recomputed = merkle_root([leaf["digest"] for leaf in leaves])
            proofs_ok = all(
                verify_proof(leaf["digest"], loads(leaf["proof_json"], []), settlement["merkle_root"])
                for leaf in leaves
            ) if leaves else True
            if recomputed != settlement["merkle_root"] or not proofs_ok:
                result = "MISMATCH"
            elif pub and pub["status"] in ("queued", "submitted"):
                result = "PENDING_PUBLICATION"
            else:
                result = "MATCH"
        self._canonical_audit(
            "SETTLEMENT_VERIFIED", settlement_id, "operator", user["user_id"],
            {"result": result, "simulated": bool(pub["simulated"]) if pub else None},
        )
        return {
            "result": result,
            "settlement_id": settlement_id,
            "merkle_root": settlement["merkle_root"],
            "manifest_digest": settlement["manifest_digest"],
            "publication_status": pub["status"] if pub else None,
            "simulated": bool(pub["simulated"]) if pub else None,
            "tx_hash": pub["tx_hash"] if pub else None,
        }

    def _settlement_row(self, property_id: str, settlement_id: str):
        from .control_plane import NotFoundError
        row = self.db.query_one(
            "SELECT * FROM settlements WHERE settlement_id=? AND property_id=?",
            (settlement_id, property_id),
        )
        if not row:
            raise NotFoundError("settlement not found", "settlement_not_found")
        return row

    @staticmethod
    def _settlement_public(row) -> dict:
        return {
            "settlement_id": row["settlement_id"],
            "property_id": row["property_id"],
            "event_id": row["event_id"],
            "session_count": row["session_count"],
            "qualified_seconds": row["qualified_seconds"],
            "manifest_digest": row["manifest_digest"],
            "merkle_root": row["merkle_root"],
            "status": row["status"],
            "created_at": row["created_at"],
        }

    # -- analytics reconciliation ------------------------------------------
    def snapshot_analytics(self, event_id: str) -> dict:
        row = self.get_event_row(event_id)
        snap = self.provider.fetch_analytics(self._event_map(row))
        tz_seconds = self.db.query_one(
            "SELECT COALESCE(SUM(qualified_seconds),0) AS s FROM view_sessions WHERE event_id=?",
            (event_id,),
        )["s"]
        tz_seconds = float(tz_seconds or 0)
        provider_minutes = snap.minutes_viewed if snap.available else None
        variance = None
        status = "PROVIDER_DATA_PENDING"
        if snap.available and provider_minutes is not None:
            variance = (provider_minutes * 60.0) - tz_seconds
            status = "compared"
        snapshot_id = "AN-" + uuid.uuid4().hex[:16]
        stamp = _now()
        self.db.execute(
            "INSERT INTO provider_analytics_snapshots(snapshot_id,event_id,video_id,window_start,"
            "window_end,provider_minutes,tz_qualified_seconds,variance_seconds,status,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (snapshot_id, event_id, snap.video_id, snap.window_start, snap.window_end,
             provider_minutes, tz_seconds, variance, status, stamp),
        )
        self._canonical_audit(
            "ANALYTICS_RECONCILED", event_id, "system", "media-provider",
            {"status": status, "tz_qualified_seconds": tz_seconds},
        )
        return {
            "snapshot_id": snapshot_id,
            "status": status,
            "provider_minutes": provider_minutes,
            "tz_qualified_seconds": tz_seconds,
            "variance_seconds": variance,
        }

    def retry_xrpl_publication(self, settlement_id: str) -> dict:
        row = self.db.query_one(
            "SELECT * FROM settlements WHERE settlement_id=?", (settlement_id,)
        )
        if not row:
            from .control_plane import NotFoundError
            raise NotFoundError("settlement not found", "settlement_not_found")
        return self.xrpl.retry(self.db, {
            "settlement_id": row["settlement_id"],
            "manifest_digest": row["manifest_digest"],
            "merkle_root": row["merkle_root"],
            "session_count": row["session_count"],
            "qualified_seconds": row["qualified_seconds"],
            "property_id": row["property_id"],
            "event_id": row["event_id"],
        })
