"""Same-port gateway, ws-ticket handshake, points ledger, and audit."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import Config, DEMO_SEED_PASSWORDS, bind_separate_websocket
from backend.control_plane import ControlPlane
from backend.db import Database
from backend.gateway import run_gateway
from backend.http_server import make_http_server
from backend.network import NetworkService
from backend.portal import PortalService
from backend.points import RULE_VERSION
from backend.seed import seed_if_empty
from backend.ws_server import Hub
from backend.ws_tickets import TICKET_TTL_SECONDS, mint_ticket

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None

MVP = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _wait_http(url: str, timeout: float = 8.0) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.05)
    raise TimeoutError(f"{url} never became ready: {last}")


def _json(method: str, url: str, body=None, token=None, origin=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if origin:
        headers["Origin"] = origin
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw.decode("utf-8", "replace")}
        return exc.code, payload, dict(exc.headers)


def _cookie_value(headers: dict, name: str) -> str | None:
    raw = headers.get("Set-Cookie") or headers.get("set-cookie") or ""
    for part in raw.split(";"):
        part = part.strip()
        if part.startswith(name + "="):
            return part.split("=", 1)[1]
    return None


async def _recv_until(ws, expected: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = max(0.05, deadline - time.time())
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
        if msg.get("type") == expected:
            return msg
    raise TimeoutError(f"did not receive {expected}")


class GatewayStack:
    def __init__(self):
        self.public_port = _free_port()
        self.origin = f"http://127.0.0.1:{self.public_port}"
        self.tmpdir = tempfile.mkdtemp(prefix="tz-gw-")
        self.cfg = Config(
            env="demo",
            http_host="127.0.0.1",
            http_port=self.public_port,
            allowed_origins=[self.origin, "http://localhost"],
            public_base_url=self.origin,
            token_secret="three-zone-demo-token-secret-CHANGE-ME-0000000000",
        )
        self.db = Database(str(Path(self.tmpdir) / "three_zone.sqlite3"))
        seed_if_empty(self.db, DEMO_SEED_PASSWORDS)
        self.cp = ControlPlane(self.db, self.cfg)
        media = str(Path(self.tmpdir) / "media")
        os.makedirs(media, exist_ok=True)
        self.httpd = make_http_server(
            self.cfg, self.cp, media, bind_host="127.0.0.1", bind_port=0
        )
        self.internal_port = self.httpd.server_address[1]
        self.http_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.hub = Hub(self.cp, PortalService(self.cp))
        self.loop = asyncio.new_event_loop()
        self.gw_thread = threading.Thread(target=self._run_gateway, daemon=True)

    def _run_gateway(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(run_gateway(self.cfg, self.hub, self.internal_port))

    def start(self):
        self.http_thread.start()
        self.gw_thread.start()
        _wait_http(f"{self.origin}/healthz")

    def stop(self):
        try:
            self.loop.call_soon_threadsafe(lambda: None)
        except Exception:
            pass
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def base(self) -> str:
        return self.origin


@unittest.skipUnless(websockets, "websockets required")
class SamePortGatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = GatewayStack()
        cls.stack.start()
        cls.base = cls.stack.base
        cls.origin = cls.stack.origin
        status, payload, member_headers = _json(
            "POST", cls.base + "/api/auth/login",
            {"username": "demo-viewer", "password": DEMO_SEED_PASSWORDS["demo-viewer"]},
            origin=cls.origin,
        )
        assert status == 200, payload
        cls.member_token = payload["session_token"]
        cls.member_cookie = _cookie_value(member_headers, "tz_member_session")
        assert cls.member_cookie, member_headers
        status, payload, _ = _json(
            "POST", cls.base + "/api/auth/login",
            {"username": "demo-owner", "password": DEMO_SEED_PASSWORDS["demo-owner"]},
            origin=cls.origin,
        )
        assert status == 200, payload
        cls.owner_token = payload["session_token"]

    @classmethod
    def tearDownClass(cls):
        cls.stack.stop()

    def test_healthz_and_config_on_public_port(self):
        status, payload, _ = _json("GET", self.base + "/healthz", origin=self.origin)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        status, cfg, _ = _json("GET", self.base + "/api/config", origin=self.origin)
        self.assertEqual(status, 200)
        self.assertTrue(cfg["ws_enabled"])
        self.assertIn("/ws/events/", cfg["ws_url_base"])
        self.assertNotIn("0.0.0.0", cfg["ws_url_base"])
        self.assertTrue(cfg["ws_url_base"].startswith("ws://127.0.0.1:"))

    def test_8765_is_not_listening(self):
        """This stack must not open a second WS listen. Port 8765 on the VM may
        belong to an older cloud-agent start and is not this process."""
        self.assertFalse(bind_separate_websocket())
        self.assertNotEqual(self.stack.public_port, 8765)
        self.assertNotEqual(self.stack.internal_port, 8765)
        self.assertNotEqual(self.stack.httpd.server_address[1], 8765)

    def test_valid_ticket_handshake_and_score(self):
        status, ticket, _ = _json(
            "POST", self.base + "/api/member/ws-ticket",
            {"event_id": "evt_mw_basketball"}, token=self.member_token, origin=self.origin,
        )
        self.assertEqual(status, 200, ticket)
        self.assertEqual(ticket["expires_in"], TICKET_TTL_SECONDS)
        self.assertTrue(ticket["ticket"])
        self.assertIn("/ws/events/evt_mw_basketball", ticket["ws_url"])

        async def _run():
            async with websockets.connect(
                ticket["ws_url"],
                origin=self.origin,
                subprotocols=["tz-session", "ticket." + ticket["ticket"]],
                open_timeout=5,
                close_timeout=2,
            ) as ws:
                snap = await _recv_until(ws, "event.state")
                self.assertEqual(snap["type"], "event.state")
                status, _, _ = _json(
                    "POST", self.base + "/api/events/evt_mw_basketball/score",
                    {"scoreboard": {"home": 12, "away": 9, "period": "Q2", "clock": "03:00"}},
                    token=self.owner_token, origin=self.origin,
                )
                self.assertEqual(status, 200)
                msg = await _recv_until(ws, "score.update")
                self.assertEqual(msg["scoreboard"]["home"], 12)
                await ws.send(json.dumps({"type": "ping"}))
                pong = await _recv_until(ws, "pong")
                self.assertEqual(pong["type"], "pong")
                return snap

        asyncio.run(_run())
        minted = self.stack.db.query_one("SELECT action FROM audit WHERE action='ws.ticket.minted' ORDER BY id DESC")
        consumed = self.stack.db.query_one("SELECT action FROM audit WHERE action='ws.ticket.consumed' ORDER BY id DESC")
        self.assertIsNotNone(minted)
        self.assertIsNotNone(consumed)

    def test_replay_ticket_rejected(self):
        status, ticket, _ = _json(
            "POST", self.base + "/api/member/ws-ticket",
            {"event_id": "evt_mw_basketball"}, token=self.member_token, origin=self.origin,
        )
        self.assertEqual(status, 200)

        async def _once():
            async with websockets.connect(
                ticket["ws_url"],
                origin=self.origin,
                subprotocols=["tz-session", "ticket." + ticket["ticket"]],
                open_timeout=5,
                close_timeout=2,
            ) as ws:
                await asyncio.wait_for(ws.recv(), timeout=5)

        asyncio.run(_once())

        async def _replay():
            try:
                async with websockets.connect(
                    ticket["ws_url"],
                    origin=self.origin,
                    subprotocols=["tz-session", "ticket." + ticket["ticket"]],
                    open_timeout=5,
                    close_timeout=2,
                ) as ws:
                    await asyncio.wait_for(ws.recv(), timeout=3)
                    return "opened"
            except Exception as exc:
                return str(exc)

        result = asyncio.run(_replay())
        self.assertNotEqual(result, "opened")
        rejected = self.stack.db.query(
            "SELECT action, detail FROM audit WHERE action='ws.ticket.rejected'"
        )
        self.assertTrue(any(r["action"] == "ws.ticket.rejected" for r in rejected))

    def test_session_token_rejected_on_handshake(self):
        async def _run():
            try:
                async with websockets.connect(
                    f"{self.base.replace('http', 'ws')}/ws/events/evt_mw_basketball",
                    origin=self.origin,
                    subprotocols=["tz-session", self.member_token],
                    open_timeout=5,
                    close_timeout=2,
                ) as ws:
                    await asyncio.wait_for(ws.recv(), timeout=3)
                    return "opened"
            except Exception as exc:
                return str(exc)

        result = asyncio.run(_run())
        self.assertNotEqual(result, "opened")

    def test_wrong_event_ticket_rejected(self):
        status, ticket, _ = _json(
            "POST", self.base + "/api/member/ws-ticket",
            {"event_id": "evt_mw_basketball"}, token=self.member_token, origin=self.origin,
        )
        self.assertEqual(status, 200)
        wrong = ticket["ws_url"].replace("evt_mw_basketball", "evt_mw_soccer")

        async def _run():
            try:
                async with websockets.connect(
                    wrong,
                    origin=self.origin,
                    subprotocols=["tz-session", "ticket." + ticket["ticket"]],
                    open_timeout=5,
                    close_timeout=2,
                ) as ws:
                    await asyncio.wait_for(ws.recv(), timeout=3)
                    return "opened"
            except Exception as exc:
                return str(exc)

        result = asyncio.run(_run())
        self.assertNotEqual(result, "opened")

    def test_expired_ticket_rejected(self):
        user = self.stack.cp.get_user("demo-viewer")
        ticket = mint_ticket(
            self.stack.cp, user, {"event_id": "evt_mw_basketball"},
            lambda kind, target: f"{self.base.replace('http', 'ws')}/ws/events/{target}",
        )
        import hashlib
        digest = hashlib.sha256(ticket["ticket"].encode("ascii")).hexdigest()
        self.stack.db.execute(
            "UPDATE ws_tickets SET expires_at=? WHERE ticket_hash=?",
            (time.time() - 1, digest),
        )

        async def _run():
            try:
                async with websockets.connect(
                    ticket["ws_url"],
                    origin=self.origin,
                    subprotocols=["tz-session", "ticket." + ticket["ticket"]],
                    open_timeout=5,
                    close_timeout=2,
                ) as ws:
                    await asyncio.wait_for(ws.recv(), timeout=3)
                    return "opened"
            except Exception as exc:
                return str(exc)

        result = asyncio.run(_run())
        self.assertNotEqual(result, "opened")

    def test_zone_denied_ticket(self):
        status, payload, _ = _json(
            "POST", self.base + "/api/member/ws-ticket",
            {"event_id": "evt_w_baseball"}, token=self.member_token, origin=self.origin,
        )
        self.assertEqual(status, 403)
        self.assertEqual(payload.get("code"), "zone_not_entitled")

    def test_rights_revoked_reaches_subscriber(self):
        status, ticket, _ = _json(
            "POST", self.base + "/api/member/ws-ticket",
            {"event_id": "evt_mw_basketball"}, token=self.member_token, origin=self.origin,
        )
        self.assertEqual(status, 200)

        async def _run():
            async with websockets.connect(
                ticket["ws_url"],
                origin=self.origin,
                subprotocols=["tz-session", "ticket." + ticket["ticket"]],
                open_timeout=5,
                close_timeout=2,
            ) as ws:
                await _recv_until(ws, "event.state")
                status, _, _ = _json(
                    "POST", self.base + "/api/events/evt_mw_basketball/rights/revoke",
                    {"reason": "test-hold"}, token=self.owner_token, origin=self.origin,
                )
                self.assertEqual(status, 200)
                msg = await _recv_until(ws, "rights.revoked")
                return msg["type"]

        self.assertEqual(asyncio.run(_run()), "rights.revoked")
        # restore so other tests keep playback
        _json(
            "POST", self.base + "/api/events/evt_mw_basketball/rights/restore",
            {}, token=self.owner_token, origin=self.origin,
        )

    def test_no_ticket_rejected(self):
        async def _run():
            try:
                async with websockets.connect(
                    f"{self.base.replace('http', 'ws')}/ws/events/evt_mw_basketball",
                    origin=self.origin,
                    subprotocols=["tz-session"],
                    open_timeout=5,
                    close_timeout=2,
                ) as ws:
                    await asyncio.wait_for(ws.recv(), timeout=3)
                    return "opened"
            except Exception as exc:
                return str(exc)

        result = asyncio.run(_run())
        self.assertNotEqual(result, "opened")

    def test_cookie_fallback_same_origin(self):
        async def _run():
            async with websockets.connect(
                f"{self.base.replace('http', 'ws')}/ws/events/evt_mw_basketball",
                origin=self.origin,
                subprotocols=["tz-session"],
                additional_headers={"Cookie": f"tz_member_session={self.member_cookie}"},
                open_timeout=5,
                close_timeout=2,
            ) as ws:
                snap = await _recv_until(ws, "event.state")
                return snap["type"]

        self.assertEqual(asyncio.run(_run()), "event.state")

    def test_drop_resume_refetches_snapshot(self):
        status, ticket, _ = _json(
            "POST", self.base + "/api/member/ws-ticket",
            {"event_id": "evt_mw_basketball"}, token=self.member_token, origin=self.origin,
        )
        self.assertEqual(status, 200)

        async def _run():
            async with websockets.connect(
                ticket["ws_url"],
                origin=self.origin,
                subprotocols=["tz-session", "ticket." + ticket["ticket"]],
                open_timeout=5,
                close_timeout=2,
            ) as ws:
                first = await _recv_until(ws, "event.state")
            status, ticket2, _ = _json(
                "POST", self.base + "/api/member/ws-ticket",
                {"event_id": "evt_mw_basketball"}, token=self.member_token, origin=self.origin,
            )
            self.assertEqual(status, 200)
            async with websockets.connect(
                ticket2["ws_url"],
                origin=self.origin,
                subprotocols=["tz-session", "ticket." + ticket2["ticket"]],
                open_timeout=5,
                close_timeout=2,
            ) as ws:
                second = await _recv_until(ws, "event.state")
            return first["type"], second["type"]

        first_type, second_type = asyncio.run(_run())
        self.assertEqual(first_type, "event.state")
        self.assertEqual(second_type, "event.state")

    def test_audit_never_logs_raw_ticket(self):
        status, ticket, _ = _json(
            "POST", self.base + "/api/member/ws-ticket",
            {"event_id": "evt_mw_basketball"}, token=self.member_token, origin=self.origin,
        )
        self.assertEqual(status, 200)
        raw = ticket["ticket"]
        rows = self.stack.db.query("SELECT action, detail FROM audit WHERE action LIKE 'ws.ticket.%'")
        blob = json.dumps([dict(row) for row in rows])
        self.assertNotIn(raw, blob)


class PointsLedgerTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        seed_if_empty(self.db, DEMO_SEED_PASSWORDS)
        self.cfg = Config(env="demo", allowed_origins=["http://localhost"])
        self.cp = ControlPlane(self.db, self.cfg)
        self.portal = PortalService(self.cp)
        from backend.media_provider import FakeProvider
        self.net = NetworkService(self.cp, self.portal, FakeProvider())
        self.viewer = self.cp.get_user("demo-viewer")
        self.owner = self.cp.get_user("demo-owner")

    def test_publish_awards_versioned_amount(self):
        post = self.net.create_post(self.viewer, {"caption": "lincoln basketball win", "sport": "basketball"})
        me_profile = self.net.ensure_profile(self.viewer)
        total = self.net.points.total_for_profile(me_profile["profile_id"])
        self.assertEqual(total["rule_version"], RULE_VERSION)
        self.assertEqual(total["total"], 10)
        row = self.db.query_one("SELECT * FROM point_ledger WHERE subject_id=?", (post["post_id"],))
        self.assertEqual(row["amount"], 10)
        self.assertEqual(row["status"], "counted")
        self.assertEqual(row["rule_version"], RULE_VERSION)

    def test_self_like_skipped_and_unlike_reverses(self):
        post = self.net.create_post(self.viewer, {"caption": "lincoln basketball", "sport": "basketball"})
        before = self.net.points.total_for_profile(self.net.ensure_profile(self.viewer)["profile_id"])["total"]
        self.net.react(self.viewer, "post", post["post_id"], "like")
        after_self = self.net.points.total_for_profile(self.net.ensure_profile(self.viewer)["profile_id"])["total"]
        self.assertEqual(after_self, before)
        other = self.cp.get_user("demo-owner")
        self.net.ensure_profile(other)
        self.net.react(other, "post", post["post_id"], "like")
        liked = self.net.points.total_for_profile(self.net.ensure_profile(self.viewer)["profile_id"])["total"]
        self.assertEqual(liked, before + 2)
        self.net.unreact(other, "post", post["post_id"], "like")
        reversed_total = self.net.points.total_for_profile(self.net.ensure_profile(self.viewer)["profile_id"])["total"]
        self.assertEqual(reversed_total, before)
        rev = self.db.query_one(
            "SELECT * FROM point_ledger WHERE subject_id=? AND status='reversed' ORDER BY recorded_at DESC",
            (post["post_id"],),
        )
        self.assertIsNotNone(rev)
        self.assertEqual(rev["amount"], -2)

    def test_member_me_matches_ledger(self):
        self.net.create_post(self.viewer, {"caption": "lincoln basketball", "sport": "basketball"})
        from backend.http_server import make_http_server
        httpd = make_http_server(self.cfg, self.cp, "/tmp", bind_host="127.0.0.1", bind_port=0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            port = httpd.server_address[1]
            token = self.cp.password_login("demo-viewer", DEMO_SEED_PASSWORDS["demo-viewer"])["session_token"]
            status, me, _ = _json(
                "GET", f"http://127.0.0.1:{port}/api/member/me", token=token,
                origin="http://localhost",
            )
            self.assertEqual(status, 200)
            profile = self.net.ensure_profile(self.viewer)
            total = self.net.points.total_for_profile(profile["profile_id"])
            self.assertEqual(me["points"]["total"], total["total"])
            self.assertEqual(me["points"]["rule_version"], RULE_VERSION)
        finally:
            httpd.shutdown()
            httpd.server_close()


class ClientContractTests(unittest.TestCase):
    def test_portal_and_ops_use_tickets(self):
        root = MVP / "backend" / "static"
        portal = (root / "portal.js").read_text(encoding="utf-8")
        app = (root / "app.js").read_text(encoding="utf-8")
        self.assertIn("/api/member/ws-ticket", portal)
        self.assertIn("ticket.", portal)
        self.assertIn("score.update", portal)
        self.assertIn("rights.revoked", portal)
        self.assertIn("points.total", portal)
        self.assertIn("2000", portal)
        self.assertIn("5000", portal)
        self.assertIn("20000", portal)
        self.assertIn("startWatchPoll", portal)
        self.assertIn("scheduleSocketReconnect", portal)
        self.assertIn("/api/member/ws-ticket", app)
        self.assertIn("ticket.", app)
        contract = (MVP / "MEMBER_LIVE_CONTRACT.md").read_text(encoding="utf-8")
        self.assertIn("single-instance", contract)
        self.assertIn("TZ-POINTS-2026.1", contract)

    def test_public_config_never_uses_bind_all_host(self):
        cfg = Config(env="demo", http_host="0.0.0.0", http_port=8100, allowed_origins=["http://localhost"])
        public = cfg.public_config()
        self.assertTrue(public["ws_enabled"])
        self.assertNotIn("0.0.0.0", public["ws_url_base"])
        self.assertIn("127.0.0.1:8100", public["ws_url_base"])


if __name__ == "__main__":
    unittest.main()
