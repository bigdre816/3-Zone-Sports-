"""Review findings for the same-port gateway + handshake tickets.

Each test pins one authorization or accounting property that an automated
reviewer flagged, so a regression fails here instead of in production.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

MVP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MVP))

from backend import ws_tickets  # noqa: E402
from backend.config import Config  # noqa: E402
from backend.db import Database  # noqa: E402


def _db() -> Database:
    path = Path(tempfile.mkdtemp(prefix="tz-tickets-")) / "t.sqlite3"
    return Database(str(path))


class TicketAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.db = _db()

    def tearDown(self):
        self.db.close()

    def _mint(self, event_id=""):
        return ws_tickets.mint(
            self.db, user_id="usr_1", credential_kind="bearer",
            credential="sess-abc", event_id=event_id,
        )[0]

    def test_event_bound_ticket_only_redeems_on_its_event(self):
        ticket = self._mint("evt_a")
        self.assertIsNone(ws_tickets.redeem(self.db, ticket, "evt_b"))

    def test_event_bound_ticket_cannot_redeem_on_a_pathless_target(self):
        """A missing event id is a different target, not a wildcard.

        The watch-party path carries no event id; an event-bound ticket must
        not slip through it. Authority narrows, never widens.
        """
        ticket = self._mint("evt_a")
        self.assertIsNone(ws_tickets.redeem(self.db, ticket, ""))

    def test_unbound_ticket_still_works_anywhere(self):
        ticket = self._mint("")
        self.assertEqual(ws_tickets.redeem(self.db, ticket, ""), ("bearer", "sess-abc"))

    def test_ticket_is_single_use(self):
        ticket = self._mint("evt_a")
        self.assertIsNotNone(ws_tickets.redeem(self.db, ticket, "evt_a"))
        self.assertIsNone(ws_tickets.redeem(self.db, ticket, "evt_a"))

    def test_failed_redeem_still_burns_the_ticket(self):
        ticket = self._mint("evt_a")
        self.assertIsNone(ws_tickets.redeem(self.db, ticket, "evt_b"))
        self.assertIsNone(ws_tickets.redeem(self.db, ticket, "evt_a"))

    def test_expired_ticket_is_rejected(self):
        ticket = ws_tickets.mint(
            self.db, user_id="usr_1", credential_kind="bearer",
            credential="sess-abc", ttl=-1,
        )[0]
        self.assertIsNone(ws_tickets.redeem(self.db, ticket, ""))


class GatewayPortAndForwardingTests(unittest.TestCase):
    def test_gateway_uses_the_resolved_ws_port(self):
        """An explicit --ws-port/TZ_WS_PORT override must reach the gateway."""
        source = (MVP / "run.py").read_text()
        self.assertIn("internal_ws = int(config.ws_port)", source)
        self.assertNotIn('os.environ.get("TZ_WS_PORT", "8765")', source)

    def test_http_client_ip_trusts_forwarding_only_from_loopback(self):
        source = (MVP / "backend" / "http_server.py").read_text()
        self.assertIn("def _client_ip(self)", source)
        self.assertIn("self.network.check_login_rate(self._client_ip())", source)

    def test_hub_client_ip_trusts_forwarding_only_from_loopback(self):
        source = (MVP / "backend" / "ws_server.py").read_text()
        self.assertIn("def _client_ip(ws, request)", source)
        self.assertIn("peer = _client_ip(ws, request)", source)


class PublicSocketUrlTests(unittest.TestCase):
    def test_bind_address_is_never_advertised(self):
        cfg = Config(ws_host="0.0.0.0", ws_port=8765)
        self.assertEqual(cfg.public_ws_url_base(), "")
        self.assertFalse(cfg.public_config()["ws_enabled"])

    def test_gateway_origin_becomes_a_wss_destination(self):
        cfg = Config(gateway_public_origin="https://example.onrender.com")
        self.assertEqual(
            cfg.public_ws_url_base(), "wss://example.onrender.com/ws/events/"
        )
        self.assertTrue(cfg.public_config()["ws_enabled"])




class TicketMintIdentityTests(unittest.TestCase):
    """POST /api/member/ws-ticket must bind the credential that authenticated.

    resolve_identity() prefers the bearer token. If minting preferred the
    cookie, a request carrying two different members' credentials would hand
    out a ticket for the wrong account.
    """

    def _server(self):
        import threading

        from backend.control_plane import ControlPlane
        from backend.http_server import make_http_server
        from backend.seed import seed_if_empty

        db = Database(":memory:")
        seed_if_empty(db)
        cfg = Config(env="demo", http_host="127.0.0.1", http_port=0,
                     allowed_origins=["https://3zonesports.com"])
        cp = ControlPlane(db, cfg)
        httpd = make_http_server(cfg, cp, tempfile.mkdtemp(prefix="tz-mint-"))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        host, port = httpd.server_address
        return f"http://{host}:{port}", cp, db

    def _register(self, base, username):
        import json
        import urllib.request

        req = urllib.request.Request(
            base + "/api/auth/register",
            data=json.dumps({"username": username, "password": "pw-" + username,
                             "display_name": username}).encode(),
            method="POST", headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())
            cookie = (resp.headers.get("Set-Cookie") or "").split(";")[0]
        token = body.get("session_token") or body.get("token") or ""
        return token, cookie

    def _mint(self, base, token=None, cookie=None):
        import json
        import urllib.error
        import urllib.request

        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(base + "/api/member/ws-ticket", data=b"{}",
                                     method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")

    def test_bearer_only_mints(self):
        base, _cp, _db = self._server()
        token, _cookie = self._register(base, "mintone")
        status, body = self._mint(base, token=token)
        self.assertEqual(status, 200, body)
        self.assertTrue(body["ticket"].startswith("ticket."))
        self.assertLessEqual(body["expires_in"], 60)

    def test_mismatched_bearer_and_cookie_is_rejected(self):
        base, _cp, _db = self._server()
        token_a, _cookie_a = self._register(base, "minta")
        _token_b, cookie_b = self._register(base, "mintb")
        status, body = self._mint(base, token=token_a, cookie=cookie_b)
        self.assertEqual(status, 401, body)
        self.assertEqual(body.get("code"), "credential_mismatch")


class ForwardedClientIpTests(unittest.TestCase):
    """The gateway, not the visitor, decides the per-IP accounting key."""

    def _head(self, extra: str = "") -> bytes:
        return (
            "GET /api/config HTTP/1.1\r\n"
            "Host: example.onrender.com\r\n"
            f"{extra}"
            "\r\n"
        ).encode()

    def _headers(self, head: bytes) -> list[str]:
        return [l for l in head.decode().split("\r\n") if ":" in l]

    def test_inbound_client_ip_header_is_stripped(self):
        from backend import gateway

        os.environ["TZ_TRUST_UPSTREAM_PROXY"] = "0"
        try:
            head = gateway._with_forwarded(
                self._head("X-TZ-Client-IP: 9.9.9.9\r\nX-Forwarded-For: 9.9.9.9\r\n"),
                "203.0.113.7", "https",
            )
        finally:
            os.environ.pop("TZ_TRUST_UPSTREAM_PROXY", None)
        headers = self._headers(head)
        self.assertIn("X-TZ-Client-IP: 203.0.113.7", headers)
        self.assertEqual(
            [h for h in headers if h.lower().startswith("x-tz-client-ip")],
            ["X-TZ-Client-IP: 203.0.113.7"],
        )
        self.assertNotIn("9.9.9.9", head.decode())

    def test_default_trust_follows_render_without_crashing(self):
        from backend import gateway

        old_trust = os.environ.pop("TZ_TRUST_UPSTREAM_PROXY", None)
        old_render = os.environ.get("RENDER")
        os.environ["RENDER"] = "true"
        try:
            self.assertTrue(gateway._trust_upstream_proxy())
            head = gateway._with_forwarded(
                self._head("X-Forwarded-For: 198.51.100.4\r\n"),
                "10.0.0.9", "https",
            )
        finally:
            if old_trust is None:
                os.environ.pop("TZ_TRUST_UPSTREAM_PROXY", None)
            else:
                os.environ["TZ_TRUST_UPSTREAM_PROXY"] = old_trust
            if old_render is None:
                os.environ.pop("RENDER", None)
            else:
                os.environ["RENDER"] = old_render
        self.assertIn("X-TZ-Client-IP: 198.51.100.4", self._headers(head))

    def test_trusted_upstream_proxy_supplies_the_real_visitor(self):
        from backend import gateway

        os.environ["TZ_TRUST_UPSTREAM_PROXY"] = "1"
        try:
            head = gateway._with_forwarded(
                self._head("X-Forwarded-For: 9.9.9.9, 198.51.100.4\r\n"),
                "10.0.0.9", "https",
            )
        finally:
            os.environ.pop("TZ_TRUST_UPSTREAM_PROXY", None)
        self.assertIn("X-TZ-Client-IP: 198.51.100.4", self._headers(head))
        self.assertNotIn("X-TZ-Client-IP: 9.9.9.9", self._headers(head))

    def test_cloudflare_connecting_ip_wins_over_spoofed_forwarded_for(self):
        from backend import gateway

        os.environ["TZ_TRUST_UPSTREAM_PROXY"] = "1"
        try:
            head = gateway._with_forwarded(
                self._head(
                    "CF-Connecting-IP: 198.51.100.4\r\n"
                    "X-Forwarded-For: 9.9.9.9, 10.0.0.9\r\n"
                ),
                "10.0.0.9", "https",
            )
        finally:
            os.environ.pop("TZ_TRUST_UPSTREAM_PROXY", None)
        self.assertIn("X-TZ-Client-IP: 198.51.100.4", self._headers(head))

    def test_keepalive_follow_up_is_rewritten(self):
        """A second HTTP request on the same TCP connection still gets X-TZ-Client-IP."""
        import asyncio

        from backend import gateway

        received: list[bytes] = []

        async def scenario() -> None:
            got_two = asyncio.Event()

            async def backend(reader, writer):
                try:
                    while True:
                        head = await reader.readuntil(b"\r\n\r\n")
                        received.append(head)
                        length = 0
                        for line in head.split(b"\r\n"):
                            if line.lower().startswith(b"content-length:"):
                                length = int(line.split(b":", 1)[1].strip() or 0)
                        if length:
                            await reader.readexactly(length)
                        writer.write(
                            b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n"
                            b"Connection: keep-alive\r\n\r\n"
                        )
                        await writer.drain()
                        if len(received) >= 2:
                            got_two.set()
                except Exception:
                    pass
                finally:
                    writer.close()

            server = await asyncio.start_server(backend, "127.0.0.1", 0)
            backend_port = server.sockets[0].getsockname()[1]
            gw = gateway.Gateway(
                "127.0.0.1", 0,
                ("127.0.0.1", backend_port),
                ("127.0.0.1", backend_port),
                "https",
            )
            gw_server = await asyncio.start_server(
                gw._handle, "127.0.0.1", 0, limit=gateway._HEAD_LIMIT
            )
            gw_port = gw_server.sockets[0].getsockname()[1]
            try:
                os.environ["TZ_TRUST_UPSTREAM_PROXY"] = "0"
                _reader, writer = await asyncio.open_connection("127.0.0.1", gw_port)
                writer.write(
                    b"POST /login HTTP/1.1\r\nHost: example\r\n"
                    b"Content-Length: 5\r\n\r\nhello"
                    b"GET /b HTTP/1.1\r\nHost: example\r\n"
                    b"X-TZ-Client-IP: 9.9.9.9\r\n\r\n"
                )
                await writer.drain()
                await asyncio.wait_for(got_two.wait(), timeout=2)
                writer.close()
                await writer.wait_closed()
            finally:
                os.environ.pop("TZ_TRUST_UPSTREAM_PROXY", None)
                gw_server.close()
                server.close()
                await gw_server.wait_closed()
                await server.wait_closed()

        asyncio.run(scenario())
        self.assertGreaterEqual(len(received), 2)
        first = received[0].decode()
        second = received[1].decode()
        self.assertIn("X-TZ-Client-IP: 127.0.0.1", first)
        self.assertIn("X-TZ-Client-IP: 127.0.0.1", second)
        self.assertNotIn("9.9.9.9", second)


class GatewayOriginSchemeTests(unittest.TestCase):
    def test_http_origin_is_never_advertised_in_production(self):
        cfg = Config(env="production", gateway_public_origin="http://example.onrender.com")
        self.assertEqual(cfg.public_ws_url_base(), "")
        self.assertFalse(cfg.public_config()["ws_enabled"])

    def test_http_origin_still_works_for_local_development(self):
        cfg = Config(env="demo", gateway_public_origin="http://127.0.0.1:8099")
        self.assertEqual(cfg.public_ws_url_base(), "ws://127.0.0.1:8099/ws/events/")


if __name__ == "__main__":
    os.chdir(str(MVP))
    unittest.main()
