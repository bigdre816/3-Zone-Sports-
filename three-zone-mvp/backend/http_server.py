"""Same-origin HTTP surface for the control plane, built on the standard
library only (``websockets`` is the app's single third-party dependency).

Every response carries strict security headers and a locked-down CSP. API and
media responses are ``no-store``. CORS is exact-origin with credentials, so the
browser may send the HTTP-only lease cookie to the media route.
"""

from __future__ import annotations

import html
import json
import os
import re
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import demo_media
from .control_plane import ControlError, ControlPlane
from .identity import bearer_from_header, resolve_identity, resolve_identity_optional
from .mastery import article_html, full_page_html, load_markdown
from .media_provider import build_provider
from .moten_adapter import MotenIntakeService
from .network import NetworkService
from .photo_storage import build_photo_storage
from .portal import PortalService

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_STATIC_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8"}
_EVENT_RE = r"(?P<event_id>evt_[a-z0-9_]+)"


def _routes():
    return [
        ("GET", re.compile(r"^/api/health$"), "h_health", "none"),
        ("GET", re.compile(r"^/healthz$"), "h_health", "none"),
        ("GET", re.compile(r"^/health$"), "h_health", "none"),
        ("GET", re.compile(r"^/api/ops/live-readiness$"), "h_live_readiness", "operator"),
        ("GET", re.compile(r"^/api/config$"), "h_config", "none"),
        ("GET", re.compile(r"^/api/public/live$"), "h_public_live", "none"),
        ("GET", re.compile(r"^/api/public/schedules$"), "h_public_schedules", "none"),
        ("GET", re.compile(r"^/api/public/archives$"), "h_public_archives", "none"),
        ("POST", re.compile(r"^/api/auth/demo-login$"), "h_login", "none"),
        ("POST", re.compile(r"^/api/auth/login$"), "h_auth_login", "none"),
        ("POST", re.compile(r"^/api/auth/register$"), "h_auth_register", "none"),
        ("POST", re.compile(r"^/api/auth/start$"), "h_auth_start", "none"),
        ("POST", re.compile(r"^/api/auth/verify$"), "h_auth_verify", "none"),
        ("POST", re.compile(r"^/api/auth/logout$"), "h_auth_logout", "none"),
        ("GET", re.compile(r"^/api/member/me$"), "h_member_me", "member"),
        ("GET", re.compile(r"^/api/member/live$"), "h_member_live", "member"),
        ("GET", re.compile(r"^/api/member/schedules$"), "h_member_schedules", "member"),
        ("GET", re.compile(r"^/api/member/archives$"), "h_member_archives", "member"),
        ("GET", re.compile(r"^/api/member/search$"), "h_member_search", "member"),
        ("GET", re.compile(r"^/api/member/feed$"), "h_member_feed", "optional"),
        ("GET", re.compile(r"^/api/member/notifications$"), "h_member_notifications", "member"),
        ("POST", re.compile(r"^/api/member/notifications/(?P<notification_id>ntf_[a-z0-9]+)/read$"), "h_member_notification_read", "member"),
        ("GET", re.compile(r"^/api/member/settings$"), "h_member_settings", "member"),
        ("POST", re.compile(r"^/api/member/settings$"), "h_member_settings_update", "member"),
        ("GET", re.compile(r"^/api/member/friends/activity$"), "h_member_friends_activity", "member"),
        ("POST", re.compile(r"^/api/member/friends/(?P<handle>[a-z][a-z0-9_]{2,31})/request$"), "h_member_friend_request", "member"),
        ("POST", re.compile(r"^/api/member/friends/(?P<handle>[a-z][a-z0-9_]{2,31})/accept$"), "h_member_friend_accept", "member"),
        ("POST", re.compile(r"^/api/member/friends/(?P<handle>[a-z][a-z0-9_]{2,31})/unfriend$"), "h_member_unfriend", "member"),
        ("POST", re.compile(r"^/api/member/blocks/(?P<handle>[a-z][a-z0-9_]{2,31})$"), "h_member_block", "member"),
        ("POST", re.compile(r"^/api/member/blocks/(?P<handle>[a-z][a-z0-9_]{2,31})/delete$"), "h_member_unblock", "member"),
        ("POST", re.compile(r"^/api/member/follows/teams/(?P<team_id>[A-Za-z0-9_-]+)$"), "h_member_follow_team", "member"),
        ("POST", re.compile(r"^/api/member/follows/teams/(?P<team_id>[A-Za-z0-9_-]+)/delete$"), "h_member_unfollow_team", "member"),
        ("GET", re.compile(r"^/api/member/studio/sources$"), "h_member_studio_sources", "member"),
        ("GET", re.compile(rf"^/api/member/events/{_EVENT_RE}/moments$"), "h_member_event_moments", "member"),
        ("GET", re.compile(rf"^/api/member/events/{_EVENT_RE}/timeline$"), "h_member_event_timeline", "member"),
        ("POST", re.compile(r"^/api/member/watch-parties$"), "h_member_party_create", "member"),
        ("GET", re.compile(r"^/api/member/watch-parties/(?P<party_id>party_[a-z0-9]+)$"), "h_member_party_get", "member"),
        ("POST", re.compile(r"^/api/member/watch-parties/(?P<party_id>party_[a-z0-9]+)/join$"), "h_member_party_join", "member"),
        ("POST", re.compile(r"^/api/member/watch-parties/(?P<party_id>party_[a-z0-9]+)/messages$"), "h_member_party_message", "member"),
        ("POST", re.compile(r"^/api/member/posts/(?P<post_id>pst_[a-z0-9]+)/share$"), "h_member_post_share", "member"),
        ("POST", re.compile(r"^/api/member/posts/(?P<post_id>pst_[a-z0-9]+)/like$"), "h_member_post_like", "member"),
        ("PUT", re.compile(r"^/api/member/posts/(?P<post_id>pst_[a-z0-9]+)/like$"), "h_member_post_like", "member"),
        ("POST", re.compile(r"^/api/member/posts/(?P<post_id>pst_[a-z0-9]+)/unlike$"), "h_member_post_unlike", "member"),
        ("DELETE", re.compile(r"^/api/member/posts/(?P<post_id>pst_[a-z0-9]+)/like$"), "h_member_post_unlike", "member"),
        ("GET", re.compile(r"^/api/member/saved$"), "h_member_saved", "member"),
        ("POST", re.compile(rf"^/api/member/events/{_EVENT_RE}/playback$"), "h_member_playback", "member"),
        ("POST", re.compile(r"^/api/member/archive/(?P<archive_id>[A-Za-z0-9_-]+)/playback$"), "h_archive_playback", "member"),
        ("POST", re.compile(r"^/api/admin/schedules/upload$"), "h_schedule_upload", "operator"),
        ("GET", re.compile(r"^/api/cameras$"), "h_cameras_list", "operator"),
        ("POST", re.compile(r"^/api/cameras$"), "h_cameras_add", "operator"),
        ("GET", re.compile(r"^/api/admin/audit/(?P<audit_id>AUD-[a-z0-9-]+)$"), "h_audit_detail", "operator"),
        ("GET", re.compile(r"^/api/admin/audit/(?P<audit_id>AUD-[a-z0-9-]+)/xrpl$"), "h_audit_detail", "operator"),
        ("POST", re.compile(r"^/internal/treasure/verify$"), "h_treasure_verify", "operator"),
        ("POST", re.compile(r"^/internal/treasure/revalidate$"), "h_treasure_verify", "operator"),
        ("POST", re.compile(r"^/internal/audit/events$"), "h_audit_publish", "operator"),
        ("GET", re.compile(r"^/api/me$"), "h_me", "session"),
        ("GET", re.compile(r"^/api/events$"), "h_events_list", "session"),
        ("POST", re.compile(r"^/api/events$"), "h_events_create", "operator"),
        ("GET", re.compile(rf"^/api/events/{_EVENT_RE}$"), "h_event_get", "session"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/playback-session$"), "h_playback", "session"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/view-sessions$"), "h_view_start", "none"),
        ("POST", re.compile(r"^/api/view-sessions/(?P<session_id>VS-[A-Za-z0-9]+)/heartbeat$"), "h_view_heartbeat", "none"),
        ("POST", re.compile(r"^/api/view-sessions/(?P<session_id>VS-[A-Za-z0-9]+)/end$"), "h_view_end", "none"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/transition$"), "h_transition", "operator"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/score$"), "h_score", "operator"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/rights/revoke$"), "h_revoke", "operator"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/rights/restore$"), "h_restore", "operator"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/ingest-token$"), "h_ingest_token", "operator"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/camera/attach$"), "h_camera_attach", "operator"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/ingest/heartbeat$"), "h_heartbeat", "none"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/media/provision$"), "h_media_provision", "operator"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/media/rotate-key$"), "h_media_rotate", "operator"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/media/sync$"), "h_media_sync", "operator"),
        ("GET", re.compile(rf"^/api/events/{_EVENT_RE}/media/status$"), "h_media_status", "operator"),
        ("GET", re.compile(rf"^/api/events/{_EVENT_RE}/settlement-manifest$"), "h_settlement_manifest", "operator"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/media/end$"), "h_media_end", "none"),
        ("POST", re.compile(r"^/api/media/webhooks/cloudflare$"), "h_cf_webhook", "none"),
        ("GET", re.compile(r"^/api/properties/(?P<property_id>[A-Za-z0-9_-]+)/settlements$"), "h_prop_settlements", "session"),
        ("GET", re.compile(r"^/api/properties/(?P<property_id>[A-Za-z0-9_-]+)/settlements/(?P<sid>SET-[A-Za-z0-9]+)$"), "h_prop_settlement", "session"),
        ("GET", re.compile(r"^/api/properties/(?P<property_id>[A-Za-z0-9_-]+)/settlements/(?P<sid>SET-[A-Za-z0-9]+)/sessions$"), "h_prop_sessions", "session"),
        ("GET", re.compile(r"^/api/properties/(?P<property_id>[A-Za-z0-9_-]+)/settlements/(?P<sid>SET-[A-Za-z0-9]+)/sessions/(?P<session_id>VS-[A-Za-z0-9]+)/proof$"), "h_prop_proof", "session"),
        ("POST", re.compile(r"^/api/properties/(?P<property_id>[A-Za-z0-9_-]+)/settlements/(?P<sid>SET-[A-Za-z0-9]+)/verify$"), "h_prop_verify", "session"),
        ("POST", re.compile(r"^/api/leases/validate$"), "h_leases_validate", "none"),
        ("GET", re.compile(r"^/api/analytics$"), "h_analytics", "session"),
        ("GET", re.compile(r"^/api/audit$"), "h_audit", "operator"),
        ("GET", re.compile(r"^/api/audit/verification-outbox$"), "h_verification_outbox", "operator"),
        ("GET", re.compile(r"^/api/moten/discovery$"), "h_moten_discovery", "operator"),
        ("GET", re.compile(r"^/api/moten/intake/jobs/(?P<job_id>mtn_[a-f0-9]+)$"), "h_moten_job", "operator"),
        ("POST", re.compile(r"^/api/moten/intake/event$"), "h_moten_event", "operator"),
        ("POST", re.compile(r"^/api/moten/intake/rights-version$"), "h_moten_rights", "operator"),
        ("POST", re.compile(r"^/api/moten/intake/revocation-event$"), "h_moten_revocation", "operator"),
        ("POST", re.compile(r"^/api/moten/intake/settlement$"), "h_moten_settlement", "operator"),
        ("GET", re.compile(r"^/api/owner/inventory$"), "h_owner_inventory", "owner"),
        ("GET", re.compile(r"^/api/owner/mastery$"), "h_owner_mastery", "owner"),
        ("POST", re.compile(r"^/api/owner/staff$"), "h_owner_staff", "owner"),
        ("GET", re.compile(rf"^/demo/media/{_EVENT_RE}\.mp4$"), "h_media", "none"),
        ("GET", re.compile(r"^/api/network/me/profile$"), "h_net_me", "member"),
        ("POST", re.compile(r"^/api/network/me/profile$"), "h_net_me_update", "member"),
        ("GET", re.compile(r"^/api/network/profiles/(?P<handle>[a-z][a-z0-9_]{2,31})$"), "h_net_profile", "optional"),
        ("POST", re.compile(r"^/api/network/profiles/(?P<handle>[a-z][a-z0-9_]{2,31})/follow$"), "h_net_follow", "member"),
        ("POST", re.compile(r"^/api/network/profiles/(?P<handle>[a-z][a-z0-9_]{2,31})/unfollow$"), "h_net_unfollow", "member"),
        ("GET", re.compile(r"^/api/network/profiles/(?P<handle>[a-z][a-z0-9_]{2,31})/(?P<tab>posts|clips|games|saved)$"), "h_net_profile_tab", "optional"),
        ("POST", re.compile(r"^/api/network/uploads$"), "h_net_upload", "member"),
        ("GET", re.compile(r"^/api/network/uploads/(?P<job_id>upl_[a-z0-9]+)$"), "h_net_upload_status", "member"),
        ("POST", re.compile(r"^/api/network/uploads/(?P<job_id>upl_[a-z0-9]+)/cancel$"), "h_net_upload_cancel", "member"),
        ("POST", re.compile(r"^/api/network/uploads/(?P<job_id>upl_[a-z0-9]+)/retry$"), "h_net_upload_retry", "member"),
        ("POST", re.compile(r"^/api/network/webhooks/media$"), "h_net_webhook", "none"),
        ("POST", re.compile(r"^/api/network/provider/fake/upload/(?P<token>[A-Za-z0-9_-]+)$"), "h_net_fake_upload", "none"),
        ("POST", re.compile(r"^/api/network/posts$"), "h_net_post_create", "member"),
        ("GET", re.compile(r"^/api/network/posts/(?P<post_id>pst_[a-z0-9]+)$"), "h_net_post_get", "optional"),
        ("POST", re.compile(r"^/api/network/posts/(?P<post_id>pst_[a-z0-9]+)$"), "h_net_post_update", "member"),
        ("POST", re.compile(r"^/api/network/posts/(?P<post_id>pst_[a-z0-9]+)/delete$"), "h_net_post_delete", "member"),
        ("GET", re.compile(r"^/api/network/feed$"), "h_net_feed", "optional"),
        ("POST", re.compile(r"^/api/network/games$"), "h_net_game_create", "member"),
        ("GET", re.compile(r"^/api/network/games/(?P<game_id>gme_[a-z0-9]+)$"), "h_net_game_get", "optional"),
        ("POST", re.compile(r"^/api/network/games/(?P<game_id>gme_[a-z0-9]+)/attach$"), "h_net_game_attach", "member"),
        ("POST", re.compile(r"^/api/network/games/(?P<game_id>gme_[a-z0-9]+)/playback$"), "h_net_game_playback", "member"),
        ("POST", re.compile(r"^/api/network/clips$"), "h_net_clip_create", "member"),
        ("GET", re.compile(r"^/api/network/clips/(?P<clip_id>clp_[a-z0-9]+)$"), "h_net_clip_get", "optional"),
        ("POST", re.compile(r"^/api/network/clips/(?P<clip_id>clp_[a-z0-9]+)/render$"), "h_net_clip_render", "member"),
        ("POST", re.compile(r"^/api/network/clips/(?P<clip_id>clp_[a-z0-9]+)/publish$"), "h_net_clip_publish", "member"),
        ("POST", re.compile(r"^/api/network/react$"), "h_net_react", "member"),
        ("POST", re.compile(r"^/api/network/unreact$"), "h_net_unreact", "member"),
        ("GET", re.compile(r"^/api/network/comments$"), "h_net_comments", "optional"),
        ("POST", re.compile(r"^/api/network/comments$"), "h_net_comment_create", "member"),
        ("POST", re.compile(r"^/api/network/comments/(?P<comment_id>cmt_[a-z0-9]+)/delete$"), "h_net_comment_delete", "member"),
        ("POST", re.compile(r"^/api/network/saves$"), "h_net_save", "member"),
        ("POST", re.compile(r"^/api/network/saves/delete$"), "h_net_unsave", "member"),
        ("POST", re.compile(r"^/api/network/shares$"), "h_net_share", "member"),
        ("GET", re.compile(r"^/api/network/inbox$"), "h_net_inbox", "member"),
        ("POST", re.compile(r"^/api/network/inbox/(?P<share_id>shr_[a-z0-9]+)/read$"), "h_net_inbox_read", "member"),
        ("POST", re.compile(r"^/api/network/reports$"), "h_net_report", "member"),
        ("GET", re.compile(r"^/api/network/review$"), "h_net_review", "operator"),
        ("POST", re.compile(r"^/api/network/review/games/(?P<game_id>gme_[a-z0-9]+)$"), "h_net_review_game", "operator"),
        ("POST", re.compile(r"^/api/network/review/cases/(?P<case_id>mod_[a-z0-9]+)$"), "h_net_review_case", "operator"),
        ("POST", re.compile(r"^/api/network/profiles/(?P<profile_id>prf_[a-z0-9]+)/verify$"), "h_net_verify", "operator"),
        ("GET", re.compile(r"^/api/network/evidence/(?P<subject_type>game|clip|post)/(?P<subject_id>[A-Za-z0-9_-]+)$"), "h_net_evidence", "owner"),
        ("GET", re.compile(r"^/api/network/evidence/(?P<subject_type>game|clip|post)/(?P<subject_id>[A-Za-z0-9_-]+)\.csv$"), "h_net_evidence_csv", "owner"),
        ("GET", re.compile(r"^/api/network/evidence/(?P<subject_type>game|clip|post)/(?P<subject_id>[A-Za-z0-9_-]+)\.html$"), "h_net_evidence_html", "owner"),
        ("GET", re.compile(r"^/api/network/media/(?P<asset_id>med_[a-z0-9]+)$"), "h_net_media", "optional"),
    ]


class _Handler(BaseHTTPRequestHandler):
    server_version = "ThreeZone/1.0"
    protocol_version = "HTTP/1.1"

    # bound by the factory
    cp: ControlPlane = None  # type: ignore
    portal: PortalService = None  # type: ignore
    network: NetworkService = None  # type: ignore
    moten: MotenIntakeService = None  # type: ignore
    media_dir: str = "data/media"
    routes = _routes()

    # -- logging: method + path + status only, never headers or bodies ----
    def log_message(self, fmt, *args):  # noqa: D401
        # Paths never contain secrets (tokens live in headers/cookies/bodies).
        return

    # -- security + CORS helpers ------------------------------------------
    def _csp(self) -> str:
        cfg = self.cp.config
        scheme = "wss" if cfg.is_production else "ws"
        ws_origin = f"{scheme}://{cfg.ws_host}:{cfg.ws_port}"
        media_src = "'self' blob: mediastream:"
        connect_src = f"'self' {ws_origin}"
        host = cfg.cloudflare_playback_host
        if host:
            media_src += " " + host
            connect_src += " " + host
        return (
            "default-src 'none'; "
            "script-src 'self'; style-src 'self'; img-src 'self' data:; "
            f"media-src {media_src}; connect-src {connect_src}; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        )

    def _origin_allowed(self) -> tuple[bool, int | None]:
        origin = self.headers.get("Origin")
        if origin is None:
            return True, None
        for index, allowed in enumerate(self.cp.config.allowed_origins):
            if origin == allowed:
                return True, index
        parsed = urlparse(origin)
        request_host = (self.headers.get("Host") or "").split(":")[0].lower()
        origin_host = (parsed.hostname or "").lower()
        if (
            origin_host
            and request_host
            and origin_host == request_host
            and parsed.scheme in ("http", "https")
        ):
            return True, None
        return False, None

    def _base_headers(self, no_store: bool = True) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", self._csp())
        if no_store:
            self.send_header("Cache-Control", "no-store")
        ok, origin_index = self._origin_allowed()
        if origin_index is not None and ok:
            self.send_header("Access-Control-Allow-Origin", self.cp.config.allowed_origins[origin_index])
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")

    @staticmethod
    def _safe_header_value(value: str) -> str:
        text = str(value)
        if "\r" in text or "\n" in text:
            raise ControlError("invalid header value", "bad_header")
        return text

    @staticmethod
    def _safe_header_name(value: str) -> str:
        text = str(value)
        if not re.fullmatch(r"[A-Za-z0-9-]+", text):
            raise ControlError("invalid header name", "bad_header")
        return text

    def _cookie_header(self, name: str, value: str, path: str, max_age: int) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_:-]+", name):
            raise ControlError("invalid cookie name", "bad_header")
        if "\r" in path or "\n" in path:
            raise ControlError("invalid cookie path", "bad_header")
        jar = SimpleCookie()
        jar[name] = value
        morsel = jar[name]
        morsel["path"] = path
        morsel["max-age"] = str(max_age)
        morsel["httponly"] = True
        morsel["samesite"] = "Lax"
        proto = (self.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
        if proto == "https":
            morsel["secure"] = True
        return morsel.OutputString()

    def _send_json(self, status: int, payload: dict, set_cookie: tuple[str, str, str, int] | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._base_headers(no_store=True)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie is not None:
            self.send_header("Set-Cookie", self._cookie_header(*set_cookie))
        self.end_headers()
        if self.command != "HEAD":
            self._safe_write(body)

    def _safe_write(self, data: bytes) -> None:
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # -- request parsing ---------------------------------------------------
    def _read_body(self, max_bytes: int | None = None) -> dict | None:
        length = int(self.headers.get("Content-Length") or 0)
        self._raw_body = b""
        if length <= 0:
            return {}
        limit = max_bytes if max_bytes is not None else self.cp.config.max_body_bytes
        if length > limit:
            self._send_json(413, {"error": "request body too large", "code": "body_too_large"})
            return None
        raw = self.rfile.read(length)
        self._raw_body = raw or b""
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON body", "code": "bad_json"})
            return None
        if not isinstance(data, dict):
            self._send_json(400, {"error": "JSON object required", "code": "bad_json"})
            return None
        return data

    def _qs(self) -> dict:
        return {key: values[0] for key, values in parse_qs(urlparse(self.path).query).items()}

    def _session_user(self):
        return resolve_identity(
            self.cp, self.portal,
            bearer_from_header(self.headers.get("Authorization")),
            self._cookie("tz_member_session"),
        )

    def _optional_user(self):
        return resolve_identity_optional(
            self.cp, self.portal,
            bearer_from_header(self.headers.get("Authorization")),
            self._cookie("tz_member_session"),
        )

    def _cookie(self, name: str) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:  # pragma: no cover - malformed cookie header
            return None
        morsel = jar.get(name)
        return morsel.value if morsel else None

    def _member_session(self):
        return self.portal.session(self._cookie("tz_member_session") or "")

    def _viewer_user(self):
        """Bearer ops/member session, or the HTTP-only member cookie."""
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return self.cp.verify_session(auth[len("Bearer "):].strip())
        session, user = self._member_session()
        return user

    # -- dispatch ----------------------------------------------------------
    def do_OPTIONS(self):
        ok, origin_index = self._origin_allowed()
        self.send_response(HTTPStatus.NO_CONTENT)
        self._base_headers(no_store=True)
        if origin_index is not None and ok:
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers",
                             "Authorization, Content-Type, X-Media-Service-Key, X-Webhook-Secret, "
                             "Webhook-Signature, X-Network-Webhook-Secret, "
                             "Tus-Resumable, Upload-Length, Upload-Metadata")
            self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str):
        path = self.path.split("?", 1)[0]

        # Reject disallowed cross-origin requests before doing any work.
        ok, _ = self._origin_allowed()
        if not ok:
            self._send_json(403, {"error": "origin not allowed", "code": "forbidden_origin"})
            return

        if method == "GET" and path in ("/", "/index.html"):
            return self._serve_static("index.html")
        if method == "GET" and path.startswith("/moment/"):
            return self.h_moment_page({"clip_id": path.split("/moment/", 1)[-1]}, {}, self._optional_user())
        if method == "GET" and path.startswith("/post/"):
            return self.h_post_page({"post_id": path.split("/post/", 1)[-1]}, {}, self._optional_user())
        if method == "GET" and path in ("/ops", "/ops.html", "/ops/"):
            return self._serve_static("ops.html")
        if method == "GET" and path in ("/app.js", "/portal.js", "/api.js", "/styles.css", "/ops.css"):
            return self._serve_static(path.lstrip("/"))
        if method == "GET" and path.startswith("/vendor/") and ".." not in path:
            return self._serve_static(path.lstrip("/"))
        if method == "GET" and path in ("/three-zone-mastery", "/THREE_ZONE_MASTERY.md"):
            return self._serve_mastery_page()
        if method == "GET" and path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self._base_headers(no_store=False)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        for m, regex, func, auth in self.routes:
            if m != method:
                continue
            match = regex.match(path)
            if not match:
                continue
            params = match.groupdict()
            body = {}
            if method in ("POST", "PUT", "DELETE"):
                limit = None
                if func == "h_cf_webhook":
                    limit = self.cp.config.webhook_max_body_bytes
                if method != "DELETE" or int(self.headers.get("Content-Length") or 0) > 0:
                    body = self._read_body(limit)
                    if body is None:
                        return  # error already sent
                else:
                    body = {}
            try:
                user = None
                if auth == "optional":
                    user = self._optional_user()
                elif auth in ("member", "session", "operator", "owner"):
                    user = self._session_user()
                    if auth == "operator":
                        self.cp.require_operator(user)
                    elif auth == "owner":
                        self.cp.require_owner(user)
                getattr(self, func)(params, body, user)
            except ControlError as exc:
                self._send_json(exc.status, {"error": str(exc), "code": exc.code})
            except Exception as exc:  # pragma: no cover - defensive 500
                self._send_json(500, {"error": "internal error", "code": "internal"})
            return

        self._send_json(404, {"error": "not found", "code": "not_found"})

    # -- static ------------------------------------------------------------
    def _serve_static(self, name: str):
        safe = os.path.normpath(name).lstrip("/")
        full = os.path.join(STATIC_DIR, safe)
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            self._send_json(404, {"error": "not found", "code": "not_found"})
            return
        ext = os.path.splitext(full)[1]
        with open(full, "rb") as handle:
            body = handle.read()
        self.send_response(200)
        self._base_headers(no_store=True)
        self.send_header("Content-Type", _STATIC_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self._safe_write(body)

    # -- API handlers ------------------------------------------------------
    def h_health(self, p, b, u):
        self._send_json(200, {
            "status": "ok",
            "service": "three-zone-api",
            "moten": {"configured": self.cp.config.moten_enabled},
        })

    def h_live_readiness(self, p, b, u):
        # Operator/owner only. Never returns secret values — only presence/validity flags.
        from .live_readiness import readiness
        self._send_json(200, readiness(self.cp.config))

    def h_config(self, p, b, u):
        self._send_json(200, self.cp.config.public_config())

    def h_public_live(self, p, b, u):
        self._send_json(200, {"events": self.portal.public_live()})

    def h_public_schedules(self, p, b, u):
        self._send_json(200, {"schedules": self.portal.public_schedules()})

    def h_public_archives(self, p, b, u):
        self._send_json(200, {"archives": self.portal.public_archives()})

    def h_login(self, p, b, u):
        result = self.cp.demo_login((b or {}).get("account", ""))
        self._send_json(200, result)

    def _auth_cookie_response(self, result: dict):
        member = self.portal.complete_auth(result["user"]["user_id"])
        sid = member.pop("session_id")
        payload = {**result, "member": member}
        self._send_json(200, payload, set_cookie=("tz_member_session", sid, "/", self.cp.config.session_ttl))

    def h_auth_login(self, p, b, u):
        self.network.check_login_rate(self.client_address[0] if self.client_address else "unknown")
        body = b or {}
        result = self.cp.password_login(body.get("username", ""), body.get("password", ""))
        self._auth_cookie_response(result)

    def h_auth_register(self, p, b, u):
        body = b or {}
        result = self.cp.register_viewer(
            body.get("username", ""), body.get("password", ""), body.get("display_name", ""),
        )
        self._auth_cookie_response(result)

    def h_auth_start(self, p, b, u):
        self._send_json(200, self.portal.start_auth((b or {}).get("identifier", "demo-viewer")))

    def h_auth_verify(self, p, b, u):
        result = self.portal.complete_auth((b or {}).get("member_id", "demo-viewer"))
        sid = result.pop("session_id")
        self._send_json(200, result, set_cookie=("tz_member_session", sid, "/", self.cp.config.session_ttl))

    def h_auth_logout(self, p, b, u):
        sid = self._cookie("tz_member_session")
        if sid: self.portal.logout(sid)
        self._send_json(200, {"ok": True}, set_cookie=("tz_member_session", "", "/", 0))

    def h_member_me(self, p, b, u):
        profile = self.network.get_own_profile(u)
        settings = self.network.get_settings(u)
        notes = self.network.list_notifications(u)
        first = (u["display_name"] or "Member").split()[0]
        self._send_json(200, {
            "member": {
                "member_id": u["user_id"],
                "display_name": u["display_name"],
                "username": profile.get("handle"),
                "avatar_url": profile.get("avatar"),
                "home_zone": profile.get("market"),
                "role": u["role"],
                "roles": [u["role"]],
                "greeting_name": first,
            },
            "profile": profile,
            "settings": settings,
            "unread_notifications": notes["unread_count"],
        })

    def h_member_feed(self, p, b, u):
        q = self._qs()
        mode = q.get("view") or q.get("mode") or "for_you"
        self._send_json(200, self.network.feed(
            u, mode, q.get("sport") or None, q.get("cursor"),
            int(q.get("limit") or 20),
        ))

    def h_member_notifications(self, p, b, u):
        self._send_json(200, self.network.list_notifications(u))

    def h_member_notification_read(self, p, b, u):
        self._send_json(200, self.network.mark_notification_read(u, p["notification_id"]))

    def h_member_settings(self, p, b, u):
        self._send_json(200, self.network.get_settings(u))

    def h_member_settings_update(self, p, b, u):
        self._send_json(200, self.network.update_settings(u, b or {}))

    def h_member_friends_activity(self, p, b, u):
        self._send_json(200, self.network.friends_activity(u))

    def h_member_friend_request(self, p, b, u):
        self._send_json(200, self.network.request_friend(u, p["handle"]))

    def h_member_friend_accept(self, p, b, u):
        self._send_json(200, self.network.accept_friend(u, p["handle"]))

    def h_member_unfriend(self, p, b, u):
        self._send_json(200, self.network.unfriend(u, p["handle"]))

    def h_member_block(self, p, b, u):
        self._send_json(200, self.network.block_member(u, p["handle"]))

    def h_member_unblock(self, p, b, u):
        self._send_json(200, self.network.unblock_member(u, p["handle"]))

    def h_member_follow_team(self, p, b, u):
        self._send_json(200, self.network.follow_team(u, p["team_id"]))

    def h_member_unfollow_team(self, p, b, u):
        self._send_json(200, self.network.unfollow_team(u, p["team_id"]))

    def h_member_studio_sources(self, p, b, u):
        self._send_json(200, self.network.studio_sources(u))

    def h_member_event_moments(self, p, b, u):
        self._send_json(200, self.network.list_event_moments(u, p["event_id"]))

    def h_member_event_timeline(self, p, b, u):
        self._send_json(200, self.network.event_timeline(u, p["event_id"]))

    def h_member_party_create(self, p, b, u):
        self._send_json(201, self.network.create_watch_party(u, b or {}))

    def h_member_party_get(self, p, b, u):
        self._send_json(200, self.network.watch_party_view(u, p["party_id"]))

    def h_member_party_join(self, p, b, u):
        self._send_json(200, self.network.join_watch_party(u, p["party_id"]))

    def h_member_party_message(self, p, b, u):
        self._send_json(201, self.network.post_watch_party_message(u, p["party_id"], b or {}))

    def h_member_post_share(self, p, b, u):
        dest = (b or {}).get("destination") or "copy_link"
        self._send_json(200, self.network.copy_link_share(u, p["post_id"], dest))

    def h_member_post_like(self, p, b, u):
        self._send_json(200, self.network.react(u, "post", p["post_id"], "like"))

    def h_member_post_unlike(self, p, b, u):
        self._send_json(200, self.network.unreact(u, "post", p["post_id"], "like"))

    def h_member_saved(self, p, b, u):
        profile = self.network.ensure_profile(u)
        self._send_json(200, self.network.profile_collection(u, profile["handle"], "saved"))

    def h_moment_page(self, p, b, u):
        clip_id = p.get("clip_id") or ""
        if not clip_id.startswith("clp_"):
            self._send_json(404, {"error": "not found", "code": "not_found"})
            return
        try:
            data = self.network.public_moment(u, clip_id)
        except Exception as exc:
            from .control_plane import ControlError
            if isinstance(exc, ControlError):
                self._send_json(exc.status, {"error": str(exc), "code": exc.code})
                return
            raise
        title = html.escape(str(data.get("caption") or "Three-Zone moment"))
        message = html.escape(str(data.get("message") or title))
        media_url = data.get("media_url") or ""
        media = (
            f"<video src='{html.escape(str(media_url), quote=True)}' controls playsinline></video>"
            if media_url else f"<p class='sub'>{message}</p>"
        )
        rights_label = html.escape(str((data.get("source") or {}).get("rights_version") or "—"))
        page = (
            "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'/>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
            f"<title>{title}</title><link rel='stylesheet' href='/styles.css'/></head>"
            f"<body class='moment-page'><header><a class='brand' href='/'>THREEZONE.</a></header>"
            f"<main><p class='eyebrow'>MOMENT</p><h1>{title}</h1>{media}"
            f"<p class='sub'>Source linked. Rights version {rights_label}</p>"
            "<p class='sub'>This page is the canonical Three-Zone origin for the clip.</p></main></body></html>"
        )
        self._send_bytes(200, "text/html; charset=utf-8", page.encode("utf-8"))

    def h_post_page(self, p, b, u):
        try:
            post = self.network.post_view(u, p["post_id"])
        except Exception as exc:
            from .control_plane import ControlError
            if isinstance(exc, ControlError):
                self._send_json(exc.status, {"error": str(exc), "code": exc.code})
                return
            raise
        self._send_json(200, {"post": post})

    def h_member_live(self, p, b, u):
        self._send_json(200, {"events": self.portal.live(u)})

    def h_member_schedules(self, p, b, u):
        self._send_json(200, {"schedules": self.portal.schedules(u)})

    def h_member_archives(self, p, b, u):
        self._send_json(200, {"archives": self.portal.archives(u)})

    def h_member_search(self, p, b, u):
        term = self._qs().get("q", "")
        self._send_json(200, {"results": self.network.enrich_search(u, term.replace("+", " "))})

    def _lease_response(self, result: dict, event_id: str) -> None:
        token = result.pop("lease_token")
        self._send_json(
            200,
            result,
            set_cookie=(f"tz_lease_{event_id}", token, f"/demo/media/{event_id}.mp4", self.cp.config.lease_ttl),
        )

    def h_member_playback(self, p, b, u):
        result = self.portal.playback_for_user(u, p["event_id"])
        self._lease_response(result, p["event_id"])

    def h_archive_playback(self, p, b, u):
        self.portal._ensure_catalog()
        archive = self.cp.db.query_one("SELECT * FROM archive_objects WHERE archive_id=?", (p["archive_id"],))
        if not archive: raise ControlError("archive not found", "archive_not_found")
        result = self.portal.playback_for_user(u, archive["event_id"], "archive")
        self._lease_response(result, archive["event_id"])

    def h_schedule_upload(self, p, b, u):
        content = (b or {}).get("csv", "").encode()
        self._send_json(200, self.portal.upload_schedule(u, (b or {}).get("filename", "upload.csv"), content))

    def h_cameras_list(self, p, b, u):
        self._send_json(200, {"cameras": self.cp.list_cameras(u)})

    def h_cameras_add(self, p, b, u):
        self._send_json(201, {"camera": self.cp.register_camera(u, b or {})})

    def h_treasure_verify(self, p, b, u):
        self._send_json(200, self.portal.verify_treasure((b or {}).get("subject_ref", "demo-viewer")))

    def h_audit_publish(self, p, b, u):
        self._send_json(200, {"publication_ids": self.portal.publish_pending(), "simulated": True})

    def h_audit_detail(self, p, b, u):
        self._send_json(200, self.portal.audit_detail(u, p["audit_id"]))

    def h_me(self, p, b, u):
        from . import tokens
        token = tokens.sign(
            self.cp.config.token_secret, "session", {"sub": u["user_id"]},
            self.cp.config.session_ttl,
        )
        self._send_json(200, {
            "user": u,
            "session_token": token,
            "home": self.cp._home_for(u),
        })

    def h_events_list(self, p, b, u):
        self._send_json(200, {"events": self.cp.list_events(u)})

    def h_events_create(self, p, b, u):
        self._send_json(201, {"event": self.cp.create_event(u, b or {})})

    def h_event_get(self, p, b, u):
        self._send_json(200, {"event": self.cp.get_event(p["event_id"], u)})

    def h_playback(self, p, b, u):
        result = self.cp.request_playback(p["event_id"], u)
        token = result.pop("lease_token")
        event_id = p["event_id"]
        self._send_json(
            200,
            result,
            set_cookie=(f"tz_lease_{event_id}", token, f"/demo/media/{event_id}.mp4", self.cp.config.lease_ttl),
        )

    def h_transition(self, p, b, u):
        target = (b or {}).get("target", "")
        self._send_json(200, {"event": self.cp.transition(p["event_id"], u, target)})

    def h_score(self, p, b, u):
        body = b or {}
        scoreboard = body.get("scoreboard", body)
        prior_row = self.cp.get_event_row(p["event_id"])
        previous = prior_row["scoreboard"]
        event = self.cp.update_score(p["event_id"], u, scoreboard if isinstance(scoreboard, dict) else {})
        self.network.ingest_score_moment(p["event_id"], scoreboard if isinstance(scoreboard, dict) else {}, previous)
        self._send_json(200, {"event": event})

    def h_revoke(self, p, b, u):
        reason = (b or {}).get("reason", "")
        event = self.cp.revoke_rights(p["event_id"], u, reason)
        self.network.restrict_derived_from_event(p["event_id"], u)
        self._send_json(200, {"event": event})

    def h_restore(self, p, b, u):
        self._send_json(200, {"event": self.cp.restore_rights(p["event_id"], u)})

    def h_ingest_token(self, p, b, u):
        source = (b or {}).get("source", "primary")
        self._send_json(201, self.cp.issue_ingest_token(p["event_id"], u, source))

    def h_camera_attach(self, p, b, u):
        body = b or {}
        self._send_json(200, self.cp.attach_station_camera(
            p["event_id"], u,
            go_live=bool(body.get("go_live", False)),
            source=body.get("source", "primary"),
        ))

    def h_heartbeat(self, p, b, u):
        b = b or {}
        result = self.cp.record_heartbeat(
            p["event_id"], b.get("ingest_token", ""), b.get("source", "primary"),
            healthy=bool(b.get("healthy", True)),
        )
        self._send_json(200, result)

    def h_media_provision(self, p, b, u):
        self._send_json(201, self.cp.provision_media(p["event_id"], u))

    def h_media_rotate(self, p, b, u):
        self._send_json(200, self.cp.rotate_media_key(p["event_id"], u))

    def h_media_sync(self, p, b, u):
        self._send_json(200, self.cp.sync_media(p["event_id"], u))

    def h_media_status(self, p, b, u):
        self._send_json(200, self.cp.media_status(p["event_id"], u))

    def h_settlement_manifest(self, p, b, u):
        self._send_json(200, self.cp.settlement_manifest(p["event_id"], u))

    def h_media_end(self, p, b, u):
        operator = None
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            try:
                candidate = self.cp.verify_session(auth[len("Bearer "):].strip())
                if candidate["role"] in ("operator", "owner", "admin"):
                    operator = candidate
            except ControlError:
                operator = None
        if operator is not None:
            self._send_json(200, {"event": self.cp.media_end(p["event_id"], operator=operator)})
            return
        key = self.headers.get("X-Media-Service-Key", "")
        self._send_json(200, {"event": self.cp.media_end(p["event_id"], key)})

    def h_cf_webhook(self, p, b, u):
        secret = self.headers.get("X-Webhook-Secret", "")
        self._send_json(200, self.cp.handle_provider_webhook(b or {}, secret))

    def h_view_start(self, p, b, u):
        user = self._viewer_user()
        result = self.cp.start_view_session(p["event_id"], user, (b or {}).get("lease_id", ""))
        self._send_json(201, result)

    def h_view_heartbeat(self, p, b, u):
        user = self._viewer_user()
        self._send_json(200, self.cp.view_heartbeat(p["session_id"], user, b or {}))

    def h_view_end(self, p, b, u):
        user = self._viewer_user()
        reason = (b or {}).get("reason", "pagehide")
        self._send_json(200, self.cp.end_view_session(p["session_id"], user, reason))

    def h_prop_settlements(self, p, b, u):
        self._send_json(200, {"settlements": self.cp.list_property_settlements(p["property_id"], u)})

    def h_prop_settlement(self, p, b, u):
        self._send_json(200, self.cp.get_property_settlement(p["property_id"], p["sid"], u))

    def h_prop_sessions(self, p, b, u):
        self._send_json(200, {"sessions": self.cp.list_settlement_sessions(p["property_id"], p["sid"], u)})

    def h_prop_proof(self, p, b, u):
        self._send_json(200, self.cp.settlement_session_proof(p["property_id"], p["sid"], p["session_id"], u))

    def h_prop_verify(self, p, b, u):
        self._send_json(200, self.cp.verify_property_settlement(p["property_id"], p["sid"], u))

    def h_leases_validate(self, p, b, u):
        key = self.headers.get("X-Media-Service-Key", "")
        from . import tokens
        if not tokens.hmac_equal(key, self.cp.config.media_service_key):
            self._send_json(403, {"error": "invalid media service key", "code": "bad_service_key"})
            return
        b = b or {}
        result = self.cp.validate_lease(b.get("event_id", ""), b.get("lease_token", ""))
        self._send_json(200 if result["valid"] else 403, result)

    def h_analytics(self, p, b, u):
        self._send_json(200, self.cp.analytics())

    def h_audit(self, p, b, u):
        self._send_json(200, {"audit": self.cp.audit_view(u)})

    def h_verification_outbox(self, p, b, u):
        self._send_json(200, {"outbox": self.cp.verification_outbox(u)})

    def h_moten_discovery(self, p, b, u):
        self._send_json(200, self.moten.discovery())

    def h_moten_job(self, p, b, u):
        try:
            self._send_json(200, self.moten.status(p["job_id"]))
        except LookupError:
            self._send_json(404, {"error": "moten intake job not found", "code": "job_not_found"})

    def h_moten_event(self, p, b, u):
        event_id = (b or {}).get("event_id", "")
        self._send_json(202, self.moten.handoff_event(u, event_id))

    def h_moten_rights(self, p, b, u):
        body = b or {}
        self._send_json(202, self.moten.handoff_rights_version(u, body.get("event_id", ""), body.get("rights_version")))

    def h_moten_revocation(self, p, b, u):
        event_id = (b or {}).get("event_id", "")
        self._send_json(202, self.moten.handoff_revocation_event(u, event_id))

    def h_moten_settlement(self, p, b, u):
        event_id = (b or {}).get("event_id", "")
        self._send_json(202, self.moten.handoff_settlement(u, event_id))

    def h_owner_inventory(self, p, b, u):
        self._send_json(200, self.cp.owner_inventory(u))

    def h_owner_mastery(self, p, b, u):
        self._send_json(200, {
            "title": "Three Zone Mastery",
            "markdown": load_markdown(),
            "html": article_html(),
        })

    def h_owner_staff(self, p, b, u):
        body = b or {}
        self._send_json(201, self.cp.issue_staff(
            u,
            body.get("username", ""),
            body.get("password", ""),
            body.get("display_name", ""),
            body.get("role", ""),
        ))

    def _serve_mastery_page(self):
        body = full_page_html().encode("utf-8")
        self.send_response(200)
        self._base_headers(no_store=True)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self._safe_write(body)

    def h_media(self, p, b, u):
        event_id = p["event_id"]
        lease = self._cookie(f"tz_lease_{event_id}")
        if not lease:
            self._send_json(403, {"error": "no playback lease", "code": "no_lease"})
            return
        result = self.cp.validate_lease(event_id, lease)
        if not result["valid"]:
            self._send_json(403, {"error": result["message"], "code": result["reason"]})
            return
        path = demo_media.ensure_media(self.media_dir, event_id)
        status, headers, body = demo_media.read_range(path, self.headers.get("Range"))
        content_range = headers.get("Content-Range")
        if content_range is not None and not re.fullmatch(r"bytes (\*/\d+|\d+-\d+/\d+)", content_range):
            self._send_json(500, {"error": "invalid content range", "code": "internal"})
            return
        self.send_response(status)
        self._base_headers(no_store=True)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(body)))
        if content_range is not None:
            self.send_header("Content-Range", content_range)
        self.end_headers()
        if self.command != "HEAD":
            self._safe_write(body)

    def _send_bytes(self, status: int, content_type: str, body: bytes):
        self.send_response(status)
        self._base_headers(no_store=True)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self._safe_write(body)

    def h_net_me(self, p, b, u):
        self._send_json(200, {"profile": self.network.get_own_profile(u)})

    def h_net_me_update(self, p, b, u):
        self._send_json(200, {"profile": self.network.update_own_profile(u, b or {})})

    def h_net_profile(self, p, b, u):
        self._send_json(200, {"profile": self.network.get_profile_by_handle(p["handle"], u)})

    def h_net_follow(self, p, b, u):
        self._send_json(200, self.network.follow(u, p["handle"]))

    def h_net_unfollow(self, p, b, u):
        self._send_json(200, self.network.unfollow(u, p["handle"]))

    def h_net_profile_tab(self, p, b, u):
        self._send_json(200, self.network.profile_collection(u, p["handle"], p["tab"]))

    def h_net_upload(self, p, b, u):
        self._send_json(201, self.network.create_upload(u, b or {}))

    def h_net_upload_status(self, p, b, u):
        self._send_json(200, self.network.upload_status(u, p["job_id"]))

    def h_net_upload_cancel(self, p, b, u):
        self._send_json(200, self.network.cancel_upload(u, p["job_id"]))

    def h_net_upload_retry(self, p, b, u):
        self._send_json(200, self.network.retry_upload(u, p["job_id"]))

    def h_net_webhook(self, p, b, u):
        headers = {}
        for key in self.headers:
            if key.lower() in ("x-network-webhook-secret", "webhook-signature"):
                headers[key] = self.headers.get(key)
        self._send_json(200, self.network.apply_webhook(
            headers, b or {}, raw_body=getattr(self, "_raw_body", b""),
        ))

    def h_net_fake_upload(self, p, b, u):
        self._send_json(200, self.network.complete_fake_upload(p["token"], b or {}))

    def h_net_post_create(self, p, b, u):
        self._send_json(201, {"post": self.network.create_post(u, b or {})})

    def h_net_post_get(self, p, b, u):
        self._send_json(200, {"post": self.network.post_view(u, p["post_id"])})

    def h_net_post_update(self, p, b, u):
        self._send_json(200, {"post": self.network.update_post(u, p["post_id"], b or {})})

    def h_net_post_delete(self, p, b, u):
        self._send_json(200, self.network.delete_post(u, p["post_id"]))

    def h_net_feed(self, p, b, u):
        q = self._qs()
        mode = q.get("view") or q.get("mode") or "for_you"
        self._send_json(200, self.network.feed(
            u, mode, q.get("sport") or None, q.get("cursor"),
            int(q.get("limit") or 20),
        ))

    def h_net_game_create(self, p, b, u):
        self._send_json(201, {"game": self.network.submit_game(u, b or {})})

    def h_net_game_get(self, p, b, u):
        self._send_json(200, {"game": self.network.game_view(u, p["game_id"])})

    def h_net_game_attach(self, p, b, u):
        self._send_json(200, {"game": self.network.attach_game_event(u, p["game_id"], (b or {}).get("event_id", ""))})

    def h_net_game_playback(self, p, b, u):
        result = self.network.game_playback(u, p["game_id"])
        token = result.pop("lease_token", None)
        set_cookie = None
        if token and result.get("event_id"):
            eid = result["event_id"]
            set_cookie = (f"tz_lease_{eid}", token, f"/demo/media/{eid}.mp4", self.cp.config.lease_ttl)
        self._send_json(200, result, set_cookie=set_cookie)

    def h_net_clip_create(self, p, b, u):
        data = b or {}
        if data.get("source_game_id"):
            clip = self.network.create_clip_definition(u, data)
        else:
            clip = self.network.create_member_clip(u, data)
        self._send_json(201, {"clip": clip})

    def h_net_clip_get(self, p, b, u):
        self._send_json(200, {"clip": self.network.clip_view(u, p["clip_id"])})

    def h_net_clip_render(self, p, b, u):
        self._send_json(200, {"clip": self.network.render_clip(u, p["clip_id"])})

    def h_net_clip_publish(self, p, b, u):
        self._send_json(200, {"post": self.network.publish_clip(u, p["clip_id"], b or {})})

    def h_net_react(self, p, b, u):
        b = b or {}
        self._send_json(200, self.network.react(u, b.get("subject_type"), b.get("subject_id"), b.get("kind", "like")))

    def h_net_unreact(self, p, b, u):
        b = b or {}
        self._send_json(200, self.network.unreact(u, b.get("subject_type"), b.get("subject_id"), b.get("kind", "like")))

    def h_net_comments(self, p, b, u):
        q = self._qs()
        self._send_json(200, self.network.list_comments(u, q.get("subject_type"), q.get("subject_id")))

    def h_net_comment_create(self, p, b, u):
        b = b or {}
        self._send_json(201, {"comment": self.network.add_comment(
            u, b.get("subject_type"), b.get("subject_id"), b.get("body", ""),
            b.get("parent_comment_id"),
        )})

    def h_net_comment_delete(self, p, b, u):
        self._send_json(200, self.network.delete_comment(u, p["comment_id"]))

    def h_net_save(self, p, b, u):
        b = b or {}
        self._send_json(200, self.network.save_item(u, b.get("subject_type"), b.get("subject_id")))

    def h_net_unsave(self, p, b, u):
        b = b or {}
        self._send_json(200, self.network.unsave_item(u, b.get("subject_type"), b.get("subject_id")))

    def h_net_share(self, p, b, u):
        self._send_json(201, self.network.send_media(u, b or {}))

    def h_net_inbox(self, p, b, u):
        self._send_json(200, self.network.inbox(u))

    def h_net_inbox_read(self, p, b, u):
        self._send_json(200, self.network.mark_share_read(u, p["share_id"]))

    def h_net_report(self, p, b, u):
        self._send_json(201, self.network.report(u, b or {}))

    def h_net_review(self, p, b, u):
        self._send_json(200, self.network.review_queue(u))

    def h_net_review_game(self, p, b, u):
        b = b or {}
        self._send_json(200, {"game": self.network.decide_game(u, p["game_id"], b.get("action", ""), b.get("reason", ""))})

    def h_net_review_case(self, p, b, u):
        b = b or {}
        self._send_json(200, self.network.decide_moderation(u, p["case_id"], b.get("action", ""), b.get("reason", "")))

    def h_net_verify(self, p, b, u):
        b = b or {}
        self._send_json(200, {"profile": self.network.set_verification(
            u, p["profile_id"], b.get("badge", ""), b.get("state", "verified"),
        )})

    def h_net_evidence(self, p, b, u):
        self._send_json(200, self.network.evidence_bundle(u, p["subject_type"], p["subject_id"]))

    def h_net_evidence_csv(self, p, b, u):
        text = self.network.evidence_csv(u, p["subject_type"], p["subject_id"])
        self._send_bytes(200, "text/csv; charset=utf-8", text.encode("utf-8"))

    def h_net_evidence_html(self, p, b, u):
        text = self.network.evidence_html(u, p["subject_type"], p["subject_id"])
        self._send_bytes(200, "text/html; charset=utf-8", text.encode("utf-8"))

    def h_net_media(self, p, b, u):
        asset, seconds = self.network.asset_for_playback(u, p["asset_id"])
        if asset["kind"] == "photo":
            svg = (
                "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 640 360'>"
                "<rect width='640' height='360' fill='#171e27'/>"
                "<text x='320' y='180' fill='#6ea8ff' text-anchor='middle' "
                "font-size='28' font-family='sans-serif'>Sports photo</text></svg>"
            )
            self._send_bytes(200, "image/svg+xml; charset=utf-8", svg.encode("utf-8"))
            return
        path = demo_media.ensure_media(self.media_dir, asset["media_asset_id"], seconds=seconds)
        status, headers, body = demo_media.read_range(path, self.headers.get("Range"))
        self.send_response(status)
        self._base_headers(no_store=True)
        for key, value in headers.items():
            if key == "Cache-Control":
                continue
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self._safe_write(body)


def make_http_server(config, cp: ControlPlane, media_dir: str,
                     provider=None, photo_storage=None) -> ThreadingHTTPServer:
    portal = PortalService(cp)
    provider = provider or build_provider(config)
    photo_storage = photo_storage or build_photo_storage(config)
    network = NetworkService(cp, portal, provider, photo_storage)
    moten = MotenIntakeService(cp)
    network.moten = moten
    handler = type("BoundHandler", (_Handler,), {
        "cp": cp, "portal": portal, "network": network, "moten": moten, "media_dir": media_dir,
    })
    httpd = ThreadingHTTPServer((config.http_host, config.http_port), handler)
    httpd.daemon_threads = True
    return httpd
