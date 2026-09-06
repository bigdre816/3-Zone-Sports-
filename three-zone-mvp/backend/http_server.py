"""Same-origin HTTP surface for the control plane, built on the standard
library only (``websockets`` is the app's single third-party dependency).

Every response carries strict security headers and a locked-down CSP. API and
media responses are ``no-store``. CORS is exact-origin with credentials, so the
browser may send the HTTP-only lease cookie to the media route.
"""

from __future__ import annotations

import json
import os
import re
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import demo_media
from .control_plane import ControlError, ControlPlane

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_STATIC_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8"}
_EVENT_RE = r"(?P<event_id>evt_[a-z0-9_]+)"


def _routes():
    return [
        ("GET", re.compile(r"^/api/health$"), "h_health", "none"),
        ("GET", re.compile(r"^/api/config$"), "h_config", "none"),
        ("POST", re.compile(r"^/api/auth/demo-login$"), "h_login", "none"),
        ("GET", re.compile(r"^/api/me$"), "h_me", "session"),
        ("GET", re.compile(r"^/api/events$"), "h_events_list", "session"),
        ("POST", re.compile(r"^/api/events$"), "h_events_create", "operator"),
        ("GET", re.compile(rf"^/api/events/{_EVENT_RE}$"), "h_event_get", "session"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/playback-session$"), "h_playback", "session"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/transition$"), "h_transition", "operator"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/score$"), "h_score", "operator"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/rights/revoke$"), "h_revoke", "operator"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/rights/restore$"), "h_restore", "operator"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/ingest-token$"), "h_ingest_token", "operator"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/ingest/heartbeat$"), "h_heartbeat", "none"),
        ("POST", re.compile(rf"^/api/events/{_EVENT_RE}/media/end$"), "h_media_end", "none"),
        ("POST", re.compile(r"^/api/leases/validate$"), "h_leases_validate", "none"),
        ("GET", re.compile(r"^/api/analytics$"), "h_analytics", "session"),
        ("GET", re.compile(r"^/api/audit$"), "h_audit", "operator"),
        ("GET", re.compile(r"^/api/audit/verification-outbox$"), "h_verification_outbox", "operator"),
        ("GET", re.compile(r"^/api/owner/inventory$"), "h_owner_inventory", "owner"),
        ("GET", re.compile(rf"^/demo/media/{_EVENT_RE}\.mp4$"), "h_media", "none"),
    ]


class _Handler(BaseHTTPRequestHandler):
    server_version = "ThreeZone/1.0"
    protocol_version = "HTTP/1.1"

    # bound by the factory
    cp: ControlPlane = None  # type: ignore
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
        return (
            "default-src 'none'; "
            "script-src 'self'; style-src 'self'; img-src 'self' data:; "
            f"media-src 'self'; connect-src 'self' {ws_origin}; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        )

    def _origin_allowed(self) -> tuple[bool, str | None]:
        origin = self.headers.get("Origin")
        if origin is None:
            return True, None
        return (origin in self.cp.config.allowed_origins), origin

    def _base_headers(self, no_store: bool = True) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", self._csp())
        if no_store:
            self.send_header("Cache-Control", "no-store")
        ok, origin = self._origin_allowed()
        if origin is not None and ok:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")

    def _send_json(self, status: int, payload: dict, extra_headers: dict | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._base_headers(no_store=True)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self._safe_write(body)

    def _safe_write(self, data: bytes) -> None:
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # -- request parsing ---------------------------------------------------
    def _read_body(self) -> dict | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > self.cp.config.max_body_bytes:
            self._send_json(413, {"error": "request body too large", "code": "body_too_large"})
            return None
        raw = self.rfile.read(length)
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

    def _session_user(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise ControlError("missing bearer session token", "missing_session")
        token = auth[len("Bearer "):].strip()
        return self.cp.verify_session(token)

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

    # -- dispatch ----------------------------------------------------------
    def do_OPTIONS(self):
        ok, origin = self._origin_allowed()
        self.send_response(HTTPStatus.NO_CONTENT)
        self._base_headers(no_store=True)
        if origin is not None and ok:
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers",
                             "Authorization, Content-Type, X-Media-Service-Key")
            self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method: str):
        path = self.path.split("?", 1)[0]

        # Reject disallowed cross-origin requests before doing any work.
        ok, origin = self._origin_allowed()
        if not ok:
            self._send_json(403, {"error": "origin not allowed", "code": "forbidden_origin"})
            return

        if method == "GET" and path in ("/", "/index.html"):
            return self._serve_static("index.html")
        if method == "GET" and path in ("/app.js", "/styles.css"):
            return self._serve_static(path.lstrip("/"))
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
            if method == "POST":
                body = self._read_body()
                if body is None:
                    return  # error already sent
            try:
                user = None
                if auth in ("session", "operator", "owner"):
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
        self._send_json(200, {"status": "ok"})

    def h_config(self, p, b, u):
        self._send_json(200, self.cp.config.public_config())

    def h_login(self, p, b, u):
        result = self.cp.demo_login((b or {}).get("account", ""))
        self._send_json(200, result)

    def h_me(self, p, b, u):
        self._send_json(200, {"user": u})

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
        cookie = (
            f"tz_lease_{event_id}={token}; Path=/demo/media/{event_id}.mp4; "
            f"Max-Age={self.cp.config.lease_ttl}; HttpOnly; SameSite=Strict"
        )
        self._send_json(200, result, extra_headers={"Set-Cookie": cookie})

    def h_transition(self, p, b, u):
        target = (b or {}).get("target", "")
        self._send_json(200, {"event": self.cp.transition(p["event_id"], u, target)})

    def h_score(self, p, b, u):
        self._send_json(200, {"event": self.cp.update_score(p["event_id"], u, (b or {}).get("scoreboard", {}))})

    def h_revoke(self, p, b, u):
        reason = (b or {}).get("reason", "")
        self._send_json(200, {"event": self.cp.revoke_rights(p["event_id"], u, reason)})

    def h_restore(self, p, b, u):
        self._send_json(200, {"event": self.cp.restore_rights(p["event_id"], u)})

    def h_ingest_token(self, p, b, u):
        source = (b or {}).get("source", "primary")
        self._send_json(201, self.cp.issue_ingest_token(p["event_id"], u, source))

    def h_heartbeat(self, p, b, u):
        b = b or {}
        result = self.cp.record_heartbeat(
            p["event_id"], b.get("ingest_token", ""), b.get("source", "primary"),
            healthy=bool(b.get("healthy", True)),
        )
        self._send_json(200, result)

    def h_media_end(self, p, b, u):
        key = self.headers.get("X-Media-Service-Key", "")
        self._send_json(200, {"event": self.cp.media_end(p["event_id"], key)})

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

    def h_owner_inventory(self, p, b, u):
        self._send_json(200, self.cp.owner_inventory(u))

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
        self.send_response(status)
        self._base_headers(no_store=True)
        for key, value in headers.items():
            if key == "Cache-Control":
                continue  # already set by _base_headers
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self._safe_write(body)


def make_http_server(config, cp: ControlPlane, media_dir: str) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (_Handler,), {"cp": cp, "media_dir": media_dir})
    httpd = ThreadingHTTPServer((config.http_host, config.http_port), handler)
    httpd.daemon_threads = True
    return httpd
