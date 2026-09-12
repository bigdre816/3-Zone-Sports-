"""Three-Zone control plane: the single authority for events, rights,
entitlement, lifecycle, playback leases, ingest health, and audit.

The player is never the authority. A viewer receives a short-lived lease only
after :meth:`request_playback` evaluates the current event and rights state, and
the same decision is repeated by :meth:`validate_lease` on every media request.
"""

from __future__ import annotations

import hashlib
import time
import uuid

from .camera_adapters import CameraSource, adapter_for
from . import tokens
from .db import Database, IntegrityError, dumps, loads
from .passwords import (
    RESERVED, hash_password, normalize_username, valid_password, valid_username,
    verify_password,
)

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
# Self-describing site model. The owner back portal prints this so the report
# documents every tier, capability, and route that makes up the website.
# ---------------------------------------------------------------------------
TIERS = [
    {
        "tier": "member",
        "label": "Member site (viewer)",
        "role": "viewer",
        "demo_account": "demo-viewer",
        "description": "Subscriber-facing catalog and player. Sees only entitled "
                       "zones/packages and receives short-lived playback leases.",
        "capabilities": [
            "Browse the catalog of events they are entitled to",
            "Request a playback lease for a live or replay event",
            "Watch managed media while the lease and rights stay valid",
            "Receive live state, score, and revocation updates over the socket",
            "Publish sports photos, clips, and full games on the member network",
            "Create derived clips in Studio without mutating the source game",
        ],
    },
    {
        "tier": "worker",
        "label": "Back worker side (operator)",
        "role": "operator",
        "demo_account": "demo-worker",
        "description": "Production staff who run events: lifecycle, rights, ingest, "
                       "scoreboard, and the audit log. No access to the owner portal.",
        "capabilities": [
            "Create events and advance the lifecycle (scheduled -> ... -> archive)",
            "Issue event-scoped ingest tokens for primary/backup encoders",
            "Revoke and restore rights during an incident",
            "Update the live scoreboard",
            "Read the operator audit log",
            "Review pending games, uploads, and sports-only moderation cases",
        ],
    },
    {
        "tier": "owner",
        "label": "Owner side (back portal)",
        "role": "owner",
        "demo_account": "demo-owner",
        "description": "Everything the worker can do, plus the owner back portal that "
                       "prints and exports every single thing in the site.",
        "capabilities": [
            "Everything on the back worker side",
            "Open the owner back portal",
            "Print the full site inventory (users, events, all rights versions, audit)",
            "Download a complete JSON export of the whole system state",
            "Export a source-to-clip evidence bundle without provider secrets",
        ],
    },
]

# Every HTTP route the website exposes, with the tier that may reach it.
SITE_ROUTES = [
    {"method": "GET", "path": "/", "tier": "public",
     "purpose": "Three-Zone Sports Access member landing and portal"},
    {"method": "GET", "path": "/portal.js", "tier": "public",
     "purpose": "Member portal presentation logic"},
    {"method": "GET", "path": "/styles.css", "tier": "public",
     "purpose": "Member portal styles"},
    {"method": "GET", "path": "/ops", "tier": "public",
     "purpose": "Operator/owner control-plane console"},
    {"method": "GET", "path": "/ops/", "tier": "public",
     "purpose": "Operator/owner control-plane console (trailing slash)"},
    {"method": "GET", "path": "/app.js", "tier": "public",
     "purpose": "Control-plane catalog, player, operator, and owner logic"},
    {"method": "GET", "path": "/ops.css", "tier": "public",
     "purpose": "Control-plane screen and print styles"},
    {"method": "GET", "path": "/three-zone-mastery", "tier": "public",
     "purpose": "Printable Three Zone Mastery article (plain English, every engine)"},
    {"method": "GET", "path": "/favicon.ico", "tier": "public",
     "purpose": "Browser icon response"},
    {"method": "GET", "path": "/api/health", "tier": "public",
     "purpose": "Liveness probe"},
    {"method": "GET", "path": "/healthz", "tier": "public",
     "purpose": "Render/platform liveness probe (alias of /api/health)"},
    {"method": "GET", "path": "/health", "tier": "public",
     "purpose": "Liveness probe alias"},
    {"method": "GET", "path": "/api/ops/live-readiness", "tier": "worker",
     "purpose": "Live publication readiness flags (no secrets)"},
    {"method": "GET", "path": "/api/ops/dashboard", "tier": "worker",
     "purpose": "Operator health / back-portal consolidated dashboard (secret-free)"},
    {"method": "GET", "path": "/api/config", "tier": "public",
     "purpose": "Public runtime config (ports, TTLs, demo accounts)"},
    {"method": "GET", "path": "/api/public/live", "tier": "public",
     "purpose": "Public live and upcoming games preview"},
    {"method": "GET", "path": "/api/public/schedules", "tier": "public",
     "purpose": "Public schedule preview"},
    {"method": "GET", "path": "/api/public/archives", "tier": "public",
     "purpose": "Public archive preview"},
    {"method": "POST", "path": "/api/auth/login", "tier": "public",
     "purpose": "Sign in with username and password"},
    {"method": "POST", "path": "/api/auth/register", "tier": "public",
     "purpose": "Create a member (viewer) account"},
    {"method": "POST", "path": "/api/auth/demo-login", "tier": "public",
     "purpose": "Sign in as a demo member/worker/owner account"},
    {"method": "POST", "path": "/api/auth/start", "tier": "public",
     "purpose": "Begin member verification"},
    {"method": "POST", "path": "/api/auth/verify", "tier": "public",
     "purpose": "Complete Treasure verification and issue a member session cookie"},
    {"method": "POST", "path": "/api/auth/logout", "tier": "public",
     "purpose": "Revoke the HTTP-only member session cookie"},
    {"method": "GET", "path": "/api/member/me", "tier": "member",
     "purpose": "Current verified member identity"},
    {"method": "GET", "path": "/api/member/live", "tier": "member",
     "purpose": "Authorized live and upcoming games"},
    {"method": "GET", "path": "/api/member/schedules", "tier": "member",
     "purpose": "Authorized team schedules"},
    {"method": "GET", "path": "/api/member/archives", "tier": "member",
     "purpose": "Authorized archive hierarchy"},
    {"method": "GET", "path": "/api/member/search", "tier": "member",
     "purpose": "Authorization-aware discovery search"},
    {"method": "POST", "path": "/api/member/events/{id}/playback", "tier": "member",
     "purpose": "Request a rights-checked playback lease"},
    {"method": "POST", "path": "/api/admin/schedules/upload", "tier": "worker",
     "purpose": "Import a versioned team schedule"},
    {"method": "GET", "path": "/api/cameras", "tier": "worker",
     "purpose": "List configured capture cameras (secret-safe)"},
    {"method": "POST", "path": "/api/cameras", "tier": "worker",
     "purpose": "Register and verify a camera source"},
    {"method": "GET", "path": "/api/admin/audit/{id}", "tier": "worker",
     "purpose": "Inspect a canonical audit event and XRPL receipt"},
    {"method": "GET", "path": "/api/me", "tier": "member",
     "purpose": "Current signed-in identity and entitlements"},
    {"method": "GET", "path": "/api/events", "tier": "member",
     "purpose": "List events the caller is entitled to see"},
    {"method": "GET", "path": "/api/events/{id}", "tier": "member",
     "purpose": "Event detail plus the caller's access decision"},
    {"method": "POST", "path": "/api/events/{id}/playback-session", "tier": "member",
     "purpose": "Request a short-lived playback lease"},
    {"method": "POST", "path": "/api/events/{id}/view-sessions", "tier": "member",
     "purpose": "Start a viewer measurement session after a valid lease"},
    {"method": "POST", "path": "/api/view-sessions/{id}/heartbeat", "tier": "member",
     "purpose": "Authenticated viewer heartbeat (15s); not operator-only"},
    {"method": "POST", "path": "/api/view-sessions/{id}/end", "tier": "member",
     "purpose": "Close a viewer measurement session"},
    {"method": "GET", "path": "/demo/media/{id}.mp4", "tier": "member",
     "purpose": "Lease-gated managed media (revalidated per request)"},
    {"method": "GET", "path": "/vendor/hls.min.js", "tier": "public",
     "purpose": "Pinned hls.js 1.5.x for HLS playback (script-src 'self')"},
    {"method": "POST", "path": "/api/leases/validate", "tier": "service",
     "purpose": "Re-run authorization for a lease token (media proxy)"},
    {"method": "POST", "path": "/api/events", "tier": "worker",
     "purpose": "Create a new event"},
    {"method": "POST", "path": "/api/events/{id}/transition", "tier": "worker",
     "purpose": "Advance the lifecycle state"},
    {"method": "POST", "path": "/api/events/{id}/score", "tier": "worker",
     "purpose": "Update the scoreboard"},
    {"method": "POST", "path": "/api/events/{id}/rights/revoke", "tier": "worker",
     "purpose": "Revoke active rights"},
    {"method": "POST", "path": "/api/events/{id}/rights/restore", "tier": "worker",
     "purpose": "Restore rights as a new version"},
    {"method": "POST", "path": "/api/events/{id}/ingest-token", "tier": "worker",
     "purpose": "Issue an event-scoped ingest token"},
    {"method": "POST", "path": "/api/events/{id}/camera/attach", "tier": "worker",
     "purpose": "Attach this station camera and optionally go live"},
    {"method": "POST", "path": "/api/events/{id}/ingest/heartbeat", "tier": "ingest",
     "purpose": "Encoder heartbeat (ingest-token scoped)"},
    {"method": "POST", "path": "/api/events/{id}/media/provision", "tier": "worker",
     "purpose": "Bind one hosted live input and return the stream key once"},
    {"method": "POST", "path": "/api/events/{id}/media/rotate-key", "tier": "worker",
     "purpose": "Rotate the hosted ingest key (returned once)"},
    {"method": "POST", "path": "/api/events/{id}/media/sync", "tier": "worker",
     "purpose": "Pull provider status, replay readiness, and analytics snapshot"},
    {"method": "GET", "path": "/api/events/{id}/media/status", "tier": "worker",
     "purpose": "Hosted input status without keys"},
    {"method": "GET", "path": "/api/events/{id}/settlement-manifest", "tier": "worker",
     "purpose": "Canonical session digests, Merkle root, and XRPL enqueue"},
    {"method": "POST", "path": "/api/events/{id}/media/end", "tier": "service",
     "purpose": "Operator or media service ends live into replay (service key or Bearer)"},
    {"method": "POST", "path": "/api/media/webhooks/cloudflare", "tier": "public",
     "purpose": "Cloudflare Stream webhook (shared secret, idempotent)"},
    {"method": "GET", "path": "/api/properties/{id}/settlements", "tier": "worker",
     "purpose": "Property-scoped settlement list (operator/owner/auditor)"},
    {"method": "GET", "path": "/api/properties/{id}/settlements/{sid}", "tier": "worker",
     "purpose": "One settlement manifest without identity payloads"},
    {"method": "GET", "path": "/api/properties/{id}/settlements/{sid}/sessions", "tier": "worker",
     "purpose": "Pseudonymous sessions in a settlement"},
    {"method": "GET", "path": "/api/properties/{id}/settlements/{sid}/sessions/{session_id}/proof", "tier": "worker",
     "purpose": "Merkle inclusion proof for one session"},
    {"method": "POST", "path": "/api/properties/{id}/settlements/{sid}/verify", "tier": "worker",
     "purpose": "MATCH|MISMATCH|INCOMPLETE|PENDING_PUBLICATION (never silent repair)"},
    {"method": "GET", "path": "/api/audit", "tier": "worker",
     "purpose": "Read the audit log"},
    {"method": "GET", "path": "/api/audit/verification-outbox", "tier": "worker",
     "purpose": "Read canonical source events for the Treasure verification adapter"},
    {"method": "GET", "path": "/api/analytics", "tier": "member",
     "purpose": "Aggregate event and socket metrics"},
    {"method": "GET", "path": "/api/owner/inventory", "tier": "owner",
     "purpose": "Owner back portal: print/export every single thing"},
    {"method": "GET", "path": "/api/owner/mastery", "tier": "owner",
     "purpose": "Owner back portal: printable Three Zone Mastery article"},
    {"method": "POST", "path": "/api/owner/staff", "tier": "owner",
     "purpose": "Owner issues an operator or owner account (staff cannot self-register)"},
    {"method": "WS", "path": "/ws/events/{id}", "tier": "member",
     "purpose": "Event-scoped live state, score, feed, lease, and rights updates"},
    {"method": "GET", "path": "/api/network/feed", "tier": "public",
     "purpose": "For You / Following / Local sports feed"},
    {"method": "GET", "path": "/api/network/me/profile", "tier": "member",
     "purpose": "Current member public profile"},
    {"method": "POST", "path": "/api/network/me/profile", "tier": "member",
     "purpose": "Update own profile (verified badges forbidden)"},
    {"method": "GET", "path": "/api/network/profiles/{handle}", "tier": "public",
     "purpose": "Public profile by handle"},
    {"method": "POST", "path": "/api/network/profiles/{handle}/follow", "tier": "member",
     "purpose": "Follow a profile"},
    {"method": "POST", "path": "/api/network/uploads", "tier": "member",
     "purpose": "Authorize a one-time direct upload (no provider token)"},
    {"method": "POST", "path": "/api/network/webhooks/media", "tier": "service",
     "purpose": "Idempotent media-provider webhook"},
    {"method": "POST", "path": "/api/network/posts", "tier": "member",
     "purpose": "Publish a sports photo or clip post"},
    {"method": "POST", "path": "/api/network/games", "tier": "member",
     "purpose": "Submit a full-game source asset"},
    {"method": "POST", "path": "/api/network/clips", "tier": "member",
     "purpose": "Create a Studio clip definition"},
    {"method": "POST", "path": "/api/network/clips/{id}/render", "tier": "member",
     "purpose": "Render a derived clip through the media adapter"},
    {"method": "POST", "path": "/api/network/clips/{id}/publish", "tier": "member",
     "purpose": "Publish, save, or prepare a derived clip"},
    {"method": "POST", "path": "/api/network/react", "tier": "member",
     "purpose": "Like a post, clip, or game"},
    {"method": "POST", "path": "/api/network/comments", "tier": "member",
     "purpose": "Add a one-level comment"},
    {"method": "POST", "path": "/api/network/saves", "tier": "member",
     "purpose": "Save a post privately"},
    {"method": "POST", "path": "/api/network/shares", "tier": "member",
     "purpose": "Send a media reference to another member"},
    {"method": "GET", "path": "/api/network/inbox", "tier": "member",
     "purpose": "Object-share inbox"},
    {"method": "POST", "path": "/api/network/reports", "tier": "member",
     "purpose": "Report content for review"},
    {"method": "GET", "path": "/api/network/review", "tier": "worker",
     "purpose": "Pending games, uploads, and moderation cases"},
    {"method": "GET", "path": "/api/network/evidence/{type}/{id}", "tier": "owner",
     "purpose": "Owner evidence bundle (JSON)"},
    {"method": "GET", "path": "/api/network/media/{id}", "tier": "member",
     "purpose": "Rights-gated UGC playback"},
]


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


from .pipeline import PipelineMixin  # noqa: E402  — after error classes so the mixin can import them


class ControlPlane(PipelineMixin):
    def __init__(self, db: Database, config, provider=None, xrpl=None):
        from .media_providers import get_provider
        from .xrpl_adapter import XrplAdapter
        self.db = db
        self.config = config
        self.provider = get_provider(config, override=provider)
        self.xrpl = xrpl if xrpl is not None else XrplAdapter(config)

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
            "properties": loads(row["properties"], []) if "properties" in row.keys() else [],
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
            "replay_pending": bool(row["replay_pending"]) if "replay_pending" in row.keys() else False,
            "media_provider": row["media_provider"] if "media_provider" in row.keys() else "demo",
            "provider_state": row["provider_state"] if "provider_state" in row.keys() else "",
            "provider_input_id": row["provider_input_id"] if "provider_input_id" in row.keys() else None,
            "property_id": row["property_id"] if "property_id" in row.keys() else None,
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
        audit_id = self.db.execute(
            "INSERT INTO audit(ts, actor, action, event_id, detail) VALUES (?,?,?,?,?)",
            (now(), actor, action, event_id, dumps(detail or {})),
        )
        # This is a source-side outbox only. It never calls XRPL or a signing
        # service; a separately trusted adapter submits it to Treasure Network.
        source_type = {
            "rights.revoked": "rights.revoked",
            "rights.restored": "rights.version.created",
            "event.created": "media.object.created",
            "feed.failover": "operation.drill.completed",
        }.get(action, action)
        payload = detail or {}
        source_event = {
            "schema": "moten.audit.event.v1",
            "event_id": f"TZ-AUD-{audit_id}",
            "event_type": source_type,
            "schema_version": "v1",
            "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "actor_type": "authorized_system",
            "actor_id": actor,
            "actor_role": "Three-Zone operator",
            "authority_source": "THREE_ZONE_KC",
            "organization_id": "THREE_ZONE_KC",
            "department": "THREE_ZONE_OPERATIONS",
            "project_family": "Three-Zone",
            "object_type": "event",
            "object_id": event_id or f"audit-{audit_id}",
            "object_version": "v1",
            "action": action,
            "decision": None,
            "reason_code": None,
            "previous_event_id": None,
            "previous_event_hash": None,
            "correlation_id": f"three-zone-audit-{audit_id}",
            "causation_id": None,
            "source_system": "three-zone-mvp",
            "environment": self.config.env,
            "payload": payload,
            "classification": "INTERNAL_AUDIT",
            "on_chain_policy": "PERMITTED",
            "legal_effect": "audit_evidence_only",
            "created_by": actor,
            "human_approval_id": None,
            "signature_profile_id": None,
        }
        source_event["payload_hash"] = hashlib.sha256(dumps(payload).encode()).hexdigest()
        raw = dumps(source_event)
        source_event["canonical_event_hash"] = hashlib.sha256(raw.encode()).hexdigest()
        self.db.execute(
            "INSERT INTO audit_verification_outbox(audit_id,event_json,created_at) VALUES (?,?,?)",
            (audit_id, dumps(source_event), now()),
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
        if account not in ("demo-viewer", "demo-worker", "demo-owner"):
            raise ValidationError("unknown demo account", "unknown_account")
        user = self.get_user(account)
        if not user:
            raise NotFoundError("demo account not provisioned", "unknown_account")
        token = tokens.sign(
            self.config.token_secret, "session", {"sub": account}, self.config.session_ttl
        )
        self.audit_log(account, "auth.demo_login")
        return {"session_token": token, "user": user, "home": self._home_for(user)}

    def _issue_session(self, user: dict, action: str) -> dict:
        token = tokens.sign(
            self.config.token_secret, "session", {"sub": user["user_id"]}, self.config.session_ttl
        )
        self.audit_log(user["user_id"], action)
        return {"session_token": token, "user": user, "home": self._home_for(user)}

    @staticmethod
    def _home_for(user: dict) -> str:
        return "/ops" if user["role"] in ("operator", "owner", "admin") else "/"

    def password_login(self, username: str, password: str) -> dict:
        username = normalize_username(username)
        row = self.db.query_one("SELECT * FROM users WHERE user_id=?", (username,))
        if not row or not verify_password(password, row["password_hash"]):
            raise AuthError("invalid username or password", "invalid_credentials")
        user = self._user_dict(row)
        if user["account_state"] != "active":
            raise ForbiddenError("account suspended", "account_suspended")
        return self._issue_session(user, "auth.login")

    def register_viewer(self, username: str, password: str, display_name: str) -> dict:
        user = self._create_account(username, password, display_name, "viewer")
        return self._issue_session(user, "auth.register")

    def issue_staff(self, actor: dict, username: str, password: str,
                    display_name: str, role: str) -> dict:
        """Owner-only: create an operator or owner. Members cannot self-register as staff."""
        self.require_owner(actor)
        role = (role or "").strip().lower()
        if role not in ("operator", "owner"):
            raise ValidationError("role must be operator or owner", "bad_role")
        user = self._create_account(username, password, display_name, role)
        self.audit_log(actor["user_id"], "auth.staff_issued", user["user_id"], {"role": role})
        return {"user": user}

    def _create_account(self, username: str, password: str, display_name: str, role: str) -> dict:
        username = normalize_username(username)
        display_name = (display_name or "").strip() or username
        if not valid_username(username) or username in RESERVED:
            raise ValidationError("username is not available", "bad_username")
        if not valid_password(password):
            raise ValidationError("password must be 8–128 characters", "bad_password")
        if self.get_user(username):
            raise ConflictError("username is not available", "username_taken")
        self.db.execute(
            "INSERT INTO users(user_id,display_name,role,account_state,subscription,"
            "zones,packages,destinations,password_hash) VALUES (?,?,?,?,?,?,?,?,?)",
            (username, display_name[:80], role, "active", "active",
             dumps(["midwest"]), dumps(["standard"]), dumps(["web"]),
             hash_password(password)),
        )
        return self.get_user(username)

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
        # Worker (operator) and owner can both run production; members cannot.
        if user["role"] not in ("operator", "owner", "admin"):
            raise ForbiddenError("operator role required", "operator_required")

    @staticmethod
    def require_owner(user: dict) -> None:
        # Owner-only surface: the back portal that prints every single thing.
        if user["role"] not in ("owner", "admin"):
            raise ForbiddenError("owner role required", "owner_required")

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

    # -- cameras -----------------------------------------------------------
    def _put_camera_secret(self, camera_id: str, field: str, value: str | None) -> str | None:
        if not value:
            return None
        ref = f"camera/{camera_id}/{field}"
        self.db.execute(
            "INSERT OR REPLACE INTO camera_secrets(secret_ref,secret_value,created_at) VALUES (?,?,?)",
            (ref, value, now()),
        )
        return ref

    def _get_camera_secret(self, secret_ref: str | None) -> str | None:
        if not secret_ref:
            return None
        row = self.db.query_one("SELECT secret_value FROM camera_secrets WHERE secret_ref=?", (secret_ref,))
        return row["secret_value"] if row else None

    @staticmethod
    def _camera_public(row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "transport": row["transport"],
            "endpoint": row["endpoint"],
            "enabled": bool(row["enabled"]),
            "status": row["status"],
            "rights_policy_id": row["rights_policy_id"],
            "has_username": bool(row["username_secret_ref"]),
            "has_password": bool(row["password_secret_ref"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_cameras(self, operator: dict) -> list[dict]:
        self.require_operator(operator)
        rows = self.db.query(
            "SELECT * FROM camera_sources ORDER BY created_at DESC, id DESC"
        )
        return [self._camera_public(row) for row in rows]

    def register_camera(self, operator: dict, data: dict) -> dict:
        self.require_operator(operator)
        name = (data.get("name") or "").strip()
        endpoint = (data.get("endpoint") or "").strip()
        transport = (data.get("transport") or "rtsp").strip().lower()
        username = (data.get("username") or "").strip() or None
        password = (data.get("password") or "").strip() or None
        rights_policy_id = (data.get("rights_policy_id") or "").strip() or None
        if not name:
            raise ValidationError("camera name is required", "camera_name_required")
        if not endpoint:
            raise ValidationError("camera endpoint is required", "camera_endpoint_required")
        if transport not in ("rtsp", "onvif"):
            raise ValidationError("unsupported camera transport", "camera_transport_unsupported")
        if transport == "rtsp" and not endpoint.lower().startswith("rtsp://"):
            raise ValidationError("rtsp endpoint must start with rtsp://", "camera_endpoint_invalid")

        camera_id = str(uuid.uuid4())
        username_ref = self._put_camera_secret(camera_id, "username", username)
        password_ref = self._put_camera_secret(camera_id, "password", password)
        candidate = CameraSource(camera_id, name, transport, endpoint, username, password)
        try:
            adapter_for(candidate).verify()
        except FileNotFoundError as exc:
            raise ValidationError("camera probe binary is unavailable", "camera_probe_unavailable") from exc
        except RuntimeError as exc:
            raise ValidationError(str(exc), "camera_unreachable") from exc
        except ValueError as exc:
            raise ValidationError(str(exc), "camera_transport_unsupported") from exc

        stamp = now()
        try:
            self.db.execute(
                "INSERT INTO camera_sources(id,name,transport,endpoint,username_secret_ref,password_secret_ref,"
                "enabled,status,rights_policy_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    camera_id,
                    name,
                    transport,
                    endpoint,
                    username_ref,
                    password_ref,
                    1,
                    "ready",
                    rights_policy_id,
                    stamp,
                    stamp,
                ),
            )
        except IntegrityError as exc:
            raise ConflictError("camera endpoint already exists", "camera_endpoint_exists") from exc
        row = self.db.query_one("SELECT * FROM camera_sources WHERE id=?", (camera_id,))
        return self._camera_public(row)

    def load_enabled_cameras(self) -> list[CameraSource]:
        rows = self.db.query(
            "SELECT id,name,transport,endpoint,username_secret_ref,password_secret_ref FROM camera_sources "
            "WHERE enabled=1 AND status='ready' ORDER BY id ASC"
        )
        cameras: list[CameraSource] = []
        for row in rows:
            secret_user = self._get_camera_secret(row["username_secret_ref"])
            secret_pass = self._get_camera_secret(row["password_secret_ref"])
            cameras.append(
                CameraSource(str(row["id"]), row["name"], row["transport"], row["endpoint"], secret_user, secret_pass)
            )
        return cameras

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
            "production_mode,active_source,scoreboard,replay_available,created_at,"
            "media_provider,property_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id, title, zone, (data.get("category") or "general"),
                "scheduled", start, (data.get("production_mode") or "single_camera"),
                "primary", "{}", 0, now(),
                self.config.live_provider_name() if hasattr(self.config, "live_provider_name") else getattr(self.config, "media_provider", "demo"),
                (data.get("property_id") or None),
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
        if healthy:
            # Column name is allowlisted (primary|backup only) — never interpolated from client input.
            if source == "primary":
                self.db.execute(
                    "UPDATE events SET primary_last_seen=? WHERE event_id=?",
                    (stamp, event_id),
                )
            else:
                self.db.execute(
                    "UPDATE events SET backup_last_seen=? WHERE event_id=?",
                    (stamp, event_id),
                )
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

    def attach_station_camera(self, event_id: str, operator: dict, *,
                              go_live: bool = False, source: str = "primary") -> dict:
        """Treat this operator station (phone/laptop camera) as the production path.

        Issues a fresh ingest heartbeat so clearance can proceed without a CLI
        encoder. When go_live is true, walks scheduled → live.
        """
        self.require_operator(operator)
        if source not in VALID_SOURCES:
            raise ValidationError("source must be primary or backup", "bad_source")
        issued = self.issue_ingest_token(event_id, operator, source)
        self.record_heartbeat(event_id, issued["ingest_token"], source, healthy=True)
        row = self.get_event_row(event_id)
        if go_live and row["status"] != "live":
            order = ("gray", "yellow", "green", "live")
            while row["status"] != "live":
                allowed = _ALLOWED_TRANSITIONS.get(row["status"], set())
                nxt = next((state for state in order if state in allowed), None)
                if not nxt:
                    break
                self.transition(event_id, operator, nxt)
                row = self.get_event_row(event_id)
        return {
            "event": self._event_dict(row),
            "camera": "station",
            "source": source,
            "production_ready": self.production_ready(row),
        }

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
        if target == "live":
            self._canonical_audit("EVENT_STARTED", event_id, "operator", operator["user_id"],
                                  {"from": current})
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

    def media_end(self, event_id: str, service_key: str | None = None, operator: dict | None = None) -> dict:
        if operator is not None:
            self.require_operator(operator)
            actor = operator["user_id"]
        else:
            if not tokens.hmac_equal(service_key or "", self.config.media_service_key):
                raise ForbiddenError("invalid media service key", "bad_service_key")
            actor = "media-service"
        row = self.get_event_row(event_id)
        if row["status"] != "live":
            raise ConflictError("only a live event can end into replay", "not_live")
        replay_available = 1
        replay_pending = 0
        if row["provider_input_id"]:
            # Bound hosted input: disable contribution and wait for a ready VOD id.
            self.provider.disable(self._event_map(row))
            replay_available = 0
            replay_pending = 1
        self.db.execute(
            "UPDATE events SET status='replay', replay_available=?, replay_pending=?, "
            "provider_state=? WHERE event_id=?",
            (replay_available, replay_pending,
             "disabled" if row["provider_input_id"] else row["provider_state"], event_id),
        )
        self._close_open_sessions_for_event(event_id, "close_event")
        self.audit_log(actor, "event.media_end", event_id, {"from": "live", "to": "replay"})
        self._canonical_audit("STREAM_ENDED", event_id, "operator" if operator else "service", actor,
                              {"replay_pending": bool(replay_pending)})
        self._outbox(event_id, "event.state", {
            "status": "replay", "reason": "media_end", "replay_pending": bool(replay_pending),
        })
        try:
            self.snapshot_analytics(event_id)
        except Exception:
            pass
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
        self._canonical_audit("RIGHTS_REVOKED", event_id, "operator", operator["user_id"],
                              {"version": rights["version"]})
        # Heartbeats fail after this because evaluate_access sees no active rights.
        # Signed HLS URLs may live until token expiry / buffer drain; a later Worker
        # is the kill switch, not this URL.
        self._close_open_sessions_for_event(event_id, "rights_revoked")
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
        elif status == "archive":
            resolved = "archive"
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
        expires_at = now() + self.config.lease_ttl
        lease = tokens.sign(
            self.config.token_secret, "lease",
            {
                "sub": user["user_id"], "event_id": event_id,
                "rights_version": decision["rights_version"], "mode": decision["mode"],
                "lease_id": lease_id,
            },
            self.config.lease_ttl,
        )
        event = self._event_map(row)
        media_url, media_type = self.provider.playback_url(event, expires_at)
        self._persist_lease(lease_id, event_id, user["user_id"],
                            decision["rights_version"], decision["mode"], self.config.lease_ttl)
        self.audit_log(user["user_id"], "playback.granted", event_id,
                       {"mode": decision["mode"], "rights_version": decision["rights_version"]})
        self._canonical_audit(
            "PLAYBACK_LEASE_ISSUED", lease_id, "system", "rights-service",
            {"event_id": event_id, "mode": decision["mode"], "media_type": media_type},
            rights_version=decision["rights_version"],
        )
        return {
            "allow": True,
            "mode": decision["mode"],
            "rights_version": decision["rights_version"],
            "lease_token": lease,
            "lease_id": lease_id,
            "lease_ttl": self.config.lease_ttl,
            "lease_expires_at": expires_at,
            "media_url": media_url,
            "media_type": media_type,
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

    def verification_outbox(self, operator: dict, limit: int = 100) -> list[dict]:
        """Trusted adapter feed; never an XRPL-direct source endpoint."""
        self.require_operator(operator)
        rows = self.db.query(
            "SELECT id,audit_id,event_json,created_at,delivered_at FROM audit_verification_outbox"
            " ORDER BY id ASC LIMIT ?", (limit,)
        )
        return [{"outbox_id": r["id"], "audit_id": r["audit_id"], "event": loads(r["event_json"], {}),
                 "created_at": r["created_at"], "delivered_at": r["delivered_at"]} for r in rows]

    # -- owner back portal -----------------------------------------------
    def _rights_full(self, row) -> dict:
        """Full rights record including every version (active + revoked)."""
        return {
            "id": row["id"],
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
            "created_at": row["created_at"],
        }

    def network_inventory_safe(self) -> dict:
        """Counts only — never provider tokens or signed URLs."""
        def count(table: str) -> int:
            try:
                row = self.db.query_one(f"SELECT COUNT(*) AS c FROM {table}")
            except Exception:
                return 0
            return int(row["c"] if row else 0)

        return {
            "profiles": count("profiles"),
            "posts": count("posts"),
            "games": count("games"),
            "clips": count("clips"),
            "reactions": count("reactions"),
            "comments": count("comments"),
            "follows": count("follows"),
            "media_assets": count("media_assets"),
        }

    def ops_dashboard(self, operator: dict, *, live_sessions=None, moten=None) -> dict:
        """Consolidated operator Health / Back portal payload — secret-free.

        Never includes stream keys, passwords, tokens, API tokens, or signing secrets.
        """
        self.require_operator(operator)

        from .config import (
            live_continuous_verify_enabled,
            live_publication_enabled,
            member_live_enabled,
            sports_verify_enabled,
        )
        from .live_readiness import readiness as live_readiness_fn

        analytics = self.analytics()
        ready_raw = live_readiness_fn(self.config)
        live_readiness = {
            "ready_to_publish_live": bool(ready_raw.get("ready_to_publish_live")),
            "blockers": list(ready_raw.get("blockers") or []),
            "warnings": list(ready_raw.get("warnings") or []),
        }

        # Rights counts
        active_row = self.db.query_one(
            "SELECT COUNT(*) AS c FROM rights WHERE active=1 AND revoked=0"
        )
        revoked_row = self.db.query_one(
            "SELECT COUNT(*) AS c FROM rights WHERE revoked=1"
        )
        total_row = self.db.query_one("SELECT COUNT(*) AS c FROM rights")
        rights = {
            "active": int(active_row["c"] if active_row else 0),
            "revoked": int(revoked_row["c"] if revoked_row else 0),
            "total_versions": int(total_row["c"] if total_row else 0),
        }

        # Live sessions (prefer service helper)
        if live_sessions is not None:
            live_payload = live_sessions.list_recent(operator, limit=20)
        else:
            try:
                from .live_sessions import LiveSessionService
                live_payload = LiveSessionService(self).list_recent(operator, limit=20)
            except Exception:
                live_payload = {"recent": [], "by_session_state": {}, "total": 0}

        # Network + moderation open
        network = dict(self.network_inventory_safe())
        try:
            mod = self.db.query_one(
                "SELECT COUNT(*) AS c FROM moderation_cases WHERE policy_decision IS NULL"
            )
            network["moderation_open"] = int(mod["c"] if mod else 0)
        except Exception:
            network["moderation_open"] = 0

        # Media names only
        media = {
            "live_provider": self.config.live_provider_name(),
            "ugc_provider": self.config.ugc_provider_name(),
            "photo_storage": self.config.photo_storage,
        }

        # Fail-closed feature flags (read only — never enable)
        ai_flag = False
        try:
            from threezone_ai.config import process_ai_enabled
            ai_flag = bool(process_ai_enabled())
        except Exception:
            ai_flag = False
        flags = {
            "MEMBER_LIVE": bool(member_live_enabled()),
            "SPORTS_VERIFY": bool(sports_verify_enabled()),
            "LIVE_PUBLICATION": bool(live_publication_enabled()),
            "LIVE_CONTINUOUS_VERIFY": bool(live_continuous_verify_enabled()),
            "AI": ai_flag,
        }

        # Moten outbox status counts
        moten_payload = {"enabled": bool(getattr(self.config, "moten_enabled", False)), "outbox": {}}
        if moten is not None:
            try:
                disc = moten.discovery()
                moten_payload = {
                    "enabled": bool(disc.get("enabled")),
                    "outbox": dict(disc.get("outbox") or {}),
                }
            except Exception:
                pass
        else:
            try:
                rows = self.db.query(
                    "SELECT status, COUNT(*) AS total FROM moten_outbox "
                    "GROUP BY status ORDER BY status ASC"
                )
                moten_payload["outbox"] = {r["status"]: r["total"] for r in rows}
            except Exception:
                pass

        # Recent audit — keys only for detail (no secret values)
        audit_recent = []
        try:
            rows = self.db.query(
                "SELECT id, ts, actor, action, event_id, detail FROM audit "
                "ORDER BY id DESC LIMIT 25"
            )
            for r in rows:
                detail = loads(r["detail"], {}) if r["detail"] else {}
                keys = sorted(detail.keys())[:24] if isinstance(detail, dict) else []
                audit_recent.append({
                    "id": r["id"],
                    "ts": r["ts"],
                    "actor": r["actor"],
                    "action": r["action"],
                    "event_id": r["event_id"],
                    "detail_keys": keys,
                })
        except Exception:
            audit_recent = []

        return {
            "generated_at": now(),
            "health": {
                "ok": True,
                "path": "/healthz",
                "note": "liveness probe alias of /api/health",
            },
            "live_readiness": live_readiness,
            "events": {
                "total": analytics.get("events_total", 0),
                "by_status": dict(analytics.get("events_by_status") or {}),
                "by_zone": dict(analytics.get("events_by_zone") or {}),
            },
            "rights": rights,
            "live_sessions": live_payload,
            "network": network,
            "media": media,
            "flags": flags,
            "moten": moten_payload,
            "audit_recent": audit_recent,
            "sockets": {
                "connections": analytics.get("socket_connections", 0),
                "per_event": dict(analytics.get("socket_per_event") or {}),
                "metrics_fresh": bool(analytics.get("socket_metrics_fresh")),
            },
        }

    def owner_inventory(self, owner: dict) -> dict:
        """The owner back portal payload: literally every part of the website.

        Returns the self-describing site map (tiers, capabilities, routes) plus a
        complete dump of every user, event, rights version (including revoked
        history), the full audit log, and current analytics/socket metrics.
        """
        self.require_owner(owner)

        users = [self._user_dict(r) for r in
                 self.db.query("SELECT * FROM users ORDER BY user_id ASC")]

        event_rows = self.db.query("SELECT * FROM events ORDER BY scheduled_start ASC")
        events = []
        for r in event_rows:
            full = self._event_dict(r)
            rights_rows = self.db.query(
                "SELECT * FROM rights WHERE event_id=? ORDER BY version ASC", (r["event_id"],)
            )
            full["rights_versions"] = [self._rights_full(rr) for rr in rights_rows]
            events.append(full)

        audit_rows = self.db.query("SELECT * FROM audit ORDER BY id ASC")
        audit = [
            {"id": a["id"], "ts": a["ts"], "actor": a["actor"], "action": a["action"],
             "event_id": a["event_id"], "detail": loads(a["detail"], {})}
            for a in audit_rows
        ]

        rights_total = self.db.query_one("SELECT COUNT(*) AS c FROM rights")
        return {
            "generated_at": now(),
            "environment": self.config.public_config(),
            "tiers": TIERS,
            "routes": SITE_ROUTES,
            "totals": {
                "users": len(users),
                "events": len(events),
                "rights_versions": rights_total["c"] if rights_total else 0,
                "audit_entries": len(audit),
            },
            "users": users,
            "events": events,
            "audit": audit,
            "analytics": self.analytics(),
            "network": self.network_inventory_safe(),
        }
