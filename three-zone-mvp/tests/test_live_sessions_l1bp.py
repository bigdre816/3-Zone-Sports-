"""L1B+ / G4-A — private server-side ingest bound to L1B live_session.

Isolated SQLite. Network-free. Proves hard bans: flag-off; non-operator denied;
client cannot force LIVE_PUBLIC / Restream / ENABLED distribution; no calls to
Restream / Cloudflare public live input / Moten / XRPL / settlement /
ControlPlane.transition(live).
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib import error, request

_MVP = Path(__file__).resolve().parents[1]
if str(_MVP) not in sys.path:
    sys.path.insert(0, str(_MVP))

from backend.config import Config, private_live_capture_enabled  # noqa: E402
from backend.control_plane import (  # noqa: E402
    ConflictError,
    ControlPlane,
    ForbiddenError,
)
from backend.db import Database  # noqa: E402
from backend.live_sessions import (  # noqa: E402
    DISTRIBUTION_DISABLED,
    FeatureDisabledError,
    INGEST_BOUND,
    INGEST_CLOSED,
    INGEST_NONE,
    INGEST_RECEIVING,
    LiveSessionService,
    PROVIDER_NAME,
    PUBLIC_STATE_LIVE_PRIVATE,
    STATE_STOPPED,
    STATE_VERIFYING_PRIVATE,
)
from backend.seed import seed_if_empty  # noqa: E402

FLAG = "THREEZONE_PRIVATE_LIVE_CAPTURE_ENABLED"


def _clear_flag() -> None:
    os.environ.pop(FLAG, None)


def _build(media_dir: str | None = None) -> tuple[ControlPlane, LiveSessionService, str]:
    cfg = Config(env="development", allowed_origins=["http://127.0.0.1:8000"])
    db = Database(":memory:")
    seed_if_empty(db)
    cp = ControlPlane(db, cfg)
    tmp = media_dir or tempfile.mkdtemp(prefix="l1bp_media_")
    return cp, LiveSessionService(cp, media_dir=tmp), tmp


class PrivateIngestServiceTests(unittest.TestCase):
    def setUp(self):
        os.environ[FLAG] = "true"
        self.cp, self.svc, self.media_dir = _build()
        self.operator = self.cp.get_user("demo-worker")
        self.owner = self.cp.get_user("demo-owner")
        self.member = self.cp.get_user("demo-viewer")
        self._moten_before = self.cp.db.query_one(
            "SELECT COUNT(*) AS c FROM moten_outbox"
        )["c"]
        self._events_before = {
            r["event_id"]: r["status"]
            for r in self.cp.db.query("SELECT event_id, status FROM events")
        }
        self._xrpl_before = self.cp.db.query_one(
            "SELECT COUNT(*) AS c FROM xrpl_publications"
        )["c"]
        self._settlements_before = self.cp.db.query_one(
            "SELECT COUNT(*) AS c FROM settlements"
        )["c"]
        self._leases_before = self.cp.db.query_one(
            "SELECT COUNT(*) AS c FROM lease_records"
        )["c"]
        self._rights_before = {
            (r["event_id"], r["version"]): (r["active"], r["revoked"])
            for r in self.cp.db.query(
                "SELECT event_id, version, active, revoked FROM rights"
            )
        }

    def tearDown(self):
        _clear_flag()

    def test_01_flag_off_blocks_bind_and_media(self):
        s = self.svc.start(self.operator, {"idempotency_key": "off1"})
        os.environ[FLAG] = "false"
        self.assertFalse(private_live_capture_enabled())
        with self.assertRaises(FeatureDisabledError) as ctx:
            self.svc.bind_private_ingest(self.operator, s["live_session_id"])
        self.assertEqual(ctx.exception.code, "private_live_capture_disabled")
        with self.assertRaises(FeatureDisabledError):
            self.svc.receive_private_media(
                self.operator, s["live_session_id"],
                {"content_base64": base64.b64encode(b"x").decode()},
            )
        row = self.cp.db.query_one(
            "SELECT private_ingest_id, private_ingest_state FROM live_sessions "
            "WHERE live_session_id=?",
            (s["live_session_id"],),
        )
        self.assertIsNone(row["private_ingest_id"])
        self.assertEqual(row["private_ingest_state"], INGEST_NONE)

    def test_02_member_denied_bind(self):
        s = self.svc.start(self.operator, {"idempotency_key": "mem1"})
        with self.assertRaises(ForbiddenError) as ctx:
            self.svc.bind_private_ingest(self.member, s["live_session_id"])
        self.assertEqual(ctx.exception.code, "operator_required")

    def test_03_bind_sets_handle_keeps_private_truth(self):
        s = self.svc.start(self.operator, {"idempotency_key": "bind1"})
        out = self.svc.bind_private_ingest(self.operator, s["live_session_id"], {
            "public_state": "LIVE_PUBLIC",
            "distribution_state": "ENABLED",
            "provider_name": "restream",
            "provider_stream_id": "cf_public_hack",
            "restream_event_id": "rst_evil",
            "private_ingest_id": "client_forged",
        })
        self.assertEqual(out["session_state"], STATE_VERIFYING_PRIVATE)
        self.assertEqual(out["public_state"], PUBLIC_STATE_LIVE_PRIVATE)
        self.assertEqual(out["distribution_state"], DISTRIBUTION_DISABLED)
        self.assertEqual(out["provider_name"], PROVIDER_NAME)
        self.assertIsNone(out["provider_stream_id"])
        self.assertIsNone(out["restream_event_id"])
        pi = out["private_ingest"]
        self.assertTrue(pi["private_ingest_id"].startswith("pi_"))
        self.assertNotEqual(pi["private_ingest_id"], "client_forged")
        self.assertEqual(pi["private_ingest_state"], INGEST_BOUND)
        self.assertFalse(pi["published"])
        self.assertIn("not published", pi["label"].lower())
        self.assertIn("Private ingest bound", out["publication"]["label"])
        self.assertFalse(out["publication"]["browser_source_published"])

    def test_04_idempotent_bind_same_session(self):
        s = self.svc.start(self.operator, {"idempotency_key": "idem-bind"})
        a = self.svc.bind_private_ingest(self.operator, s["live_session_id"])
        b = self.svc.bind_private_ingest(self.operator, s["live_session_id"])
        self.assertEqual(
            a["private_ingest"]["private_ingest_id"],
            b["private_ingest"]["private_ingest_id"],
        )

    def test_05_receive_media_private_only(self):
        s = self.svc.start(self.operator, {"idempotency_key": "media1"})
        self.svc.bind_private_ingest(self.operator, s["live_session_id"])
        payload = b"private-frame-bytes-l1bp"
        out = self.svc.receive_private_media(self.operator, s["live_session_id"], {
            "content_base64": base64.b64encode(payload).decode(),
            "public_state": "LIVE_PUBLIC",
            "distribution_state": "ENABLED",
            "restream_event_id": "rst_nope",
        })
        self.assertEqual(out["private_ingest"]["private_ingest_state"], INGEST_RECEIVING)
        self.assertEqual(out["private_ingest"]["private_ingest_byte_count"], len(payload))
        self.assertTrue(out["source_asset_id"].startswith("priv_asset_"))
        self.assertEqual(out["public_state"], PUBLIC_STATE_LIVE_PRIVATE)
        self.assertEqual(out["distribution_state"], DISTRIBUTION_DISABLED)
        self.assertIsNone(out["restream_event_id"])
        self.assertIsNone(out["provider_stream_id"])
        asset_path = (
            Path(self.media_dir) / "private_ingest" / s["live_session_id"]
            / f"{out['source_asset_id']}.bin"
        )
        self.assertTrue(asset_path.is_file())
        self.assertEqual(asset_path.read_bytes(), payload)

    def test_06_media_without_bind_fails(self):
        s = self.svc.start(self.operator, {"idempotency_key": "nobind"})
        with self.assertRaises(ConflictError) as ctx:
            self.svc.receive_private_media(
                self.operator, s["live_session_id"],
                {"content_base64": base64.b64encode(b"x").decode()},
            )
        self.assertEqual(ctx.exception.code, "private_ingest_not_bound")

    def test_07_stop_closes_ingest_still_private(self):
        s = self.svc.start(self.operator, {"idempotency_key": "stop-ing"})
        self.svc.bind_private_ingest(self.operator, s["live_session_id"])
        out = self.svc.stop(self.operator, s["live_session_id"], {"reason": "done"})
        self.assertEqual(out["session_state"], STATE_STOPPED)
        self.assertEqual(out["private_ingest"]["private_ingest_state"], INGEST_CLOSED)
        self.assertEqual(out["public_state"], PUBLIC_STATE_LIVE_PRIVATE)
        self.assertEqual(out["distribution_state"], DISTRIBUTION_DISABLED)
        with self.assertRaises(ConflictError) as ctx:
            self.svc.bind_private_ingest(self.operator, s["live_session_id"])
        self.assertIn(ctx.exception.code, (
            "illegal_private_ingest_state",
            "private_ingest_closed",
        ))

    def test_08_no_provider_restream_cloudflare_moten_xrpl_settlement_transition(self):
        """Hard bans: no public rails / Moten / XRPL / settlement / transition(live)."""
        provision_calls: list = []
        transition_calls: list = []

        real_transition = self.cp.transition

        def wrapped_transition(event_id, operator, target):
            transition_calls.append((event_id, target))
            return real_transition(event_id, operator, target)

        with mock.patch.object(self.cp, "transition", side_effect=wrapped_transition):
            with mock.patch(
                "backend.media_providers.cloudflare.CloudflareProvider.provision",
                side_effect=lambda *a, **k: provision_calls.append(("cf", a, k)) or (_ for _ in ()).throw(
                    AssertionError("Cloudflare provision must not be called")
                ),
            ):
                with mock.patch(
                    "backend.media_providers.demo.DemoProvider.provision",
                    side_effect=lambda *a, **k: provision_calls.append(("demo", a, k)) or (_ for _ in ()).throw(
                        AssertionError("Demo provision must not be called")
                    ),
                ):
                    s = self.svc.start(self.operator, {
                        "idempotency_key": "bans",
                        "event_id": "evt_mw_basketball",
                    })
                    self.svc.bind_private_ingest(self.operator, s["live_session_id"], {
                        "distribution_state": "ENABLED",
                        "public_state": "LIVE_PUBLIC",
                        "provider_name": "cloudflare",
                    })
                    self.svc.receive_private_media(self.operator, s["live_session_id"], {
                        "content_base64": base64.b64encode(b"abc").decode(),
                    })
                    self.svc.stop(self.operator, s["live_session_id"])

        self.assertEqual(provision_calls, [])
        self.assertEqual(transition_calls, [])
        # Event lifecycle / rights / leases unchanged.
        after_events = {
            r["event_id"]: r["status"]
            for r in self.cp.db.query("SELECT event_id, status FROM events")
        }
        self.assertEqual(self._events_before, after_events)
        self.assertEqual(
            self.cp.db.query_one("SELECT COUNT(*) AS c FROM moten_outbox")["c"],
            self._moten_before,
        )
        self.assertEqual(
            self.cp.db.query_one("SELECT COUNT(*) AS c FROM xrpl_publications")["c"],
            self._xrpl_before,
        )
        self.assertEqual(
            self.cp.db.query_one("SELECT COUNT(*) AS c FROM settlements")["c"],
            self._settlements_before,
        )
        self.assertEqual(
            self.cp.db.query_one("SELECT COUNT(*) AS c FROM lease_records")["c"],
            self._leases_before,
        )
        after_rights = {
            (r["event_id"], r["version"]): (r["active"], r["revoked"])
            for r in self.cp.db.query(
                "SELECT event_id, version, active, revoked FROM rights"
            )
        }
        self.assertEqual(self._rights_before, after_rights)
        row = self.cp.db.query_one(
            "SELECT provider_name, provider_stream_id, restream_event_id, "
            "distribution_state, public_state, private_ingest_state "
            "FROM live_sessions WHERE live_session_id=?",
            (s["live_session_id"],),
        )
        self.assertEqual(row["provider_name"], "local_browser")
        self.assertIsNone(row["provider_stream_id"])
        self.assertIsNone(row["restream_event_id"])
        self.assertEqual(row["distribution_state"], "DISABLED")
        self.assertEqual(row["public_state"], "LIVE_PRIVATE")
        self.assertEqual(row["private_ingest_state"], INGEST_CLOSED)
        # Audit trail is live_session.* only for this subject — no event.transition.
        audits = self.cp.db.query(
            "SELECT action FROM audit WHERE event_id=?",
            (s["live_session_id"],),
        )
        actions = {a["action"] for a in audits}
        self.assertIn("live_session.private_ingest_bound", actions)
        self.assertIn("live_session.private_ingest_media", actions)
        self.assertNotIn("event.transition", actions)

    def test_09_schema_private_ingest_columns(self):
        rows = self.cp.db.query("PRAGMA table_info(live_sessions)")
        cols = set()
        for r in rows:
            try:
                cols.add(r["name"])
            except Exception:
                cols.add(r[1])
        required = {
            "private_ingest_id",
            "private_ingest_state",
            "private_ingest_bound_at",
            "private_ingest_closed_at",
            "private_ingest_byte_count",
        }
        self.assertTrue(required.issubset(cols), f"missing {required - cols}")
        from backend.db import SCHEMA, _postgres_schema
        self.assertIn("private_ingest_id", SCHEMA)
        self.assertIn("private_ingest_id", _postgres_schema())


class PrivateIngestHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ[FLAG] = "true"
        from backend.http_server import make_http_server

        cls._tmpdir = tempfile.mkdtemp(prefix="l1bp_http_")
        cfg = Config(
            env="development",
            http_host="127.0.0.1",
            http_port=0,
            allowed_origins=["http://127.0.0.1"],
        )
        db = Database(":memory:")
        seed_if_empty(db)
        cls.cp = ControlPlane(db, cfg)
        cls.httpd = make_http_server(cfg, cls.cp, media_dir=cls._tmpdir)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.op_token = cls.cp.demo_login("demo-worker")["session_token"]
        cls.member_token = cls.cp.demo_login("demo-viewer")["session_token"]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        _clear_flag()

    def setUp(self):
        os.environ[FLAG] = "true"

    def _call(self, method: str, path: str, token: str | None = None, body: dict | None = None):
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode())
        except error.HTTPError as exc:
            payload = exc.read().decode()
            try:
                parsed = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                parsed = {"raw": payload}
            return exc.code, parsed

    def test_10_http_bind_media_member_denied_flag_off(self):
        st, payload = self._call(
            "POST", "/api/live-sessions",
            token=self.op_token,
            body={"idempotency_key": "http-l1bp"},
        )
        self.assertEqual(st, 201)
        sid = payload["live_session"]["live_session_id"]

        st, body = self._call(
            "POST", f"/api/live-sessions/{sid}/private-ingest",
            token=self.op_token,
            body={"distribution_state": "ENABLED", "public_state": "LIVE_PUBLIC"},
        )
        self.assertEqual(st, 200)
        ls = body["live_session"]
        self.assertEqual(ls["distribution_state"], "DISABLED")
        self.assertEqual(ls["public_state"], "LIVE_PRIVATE")
        self.assertEqual(ls["private_ingest"]["private_ingest_state"], INGEST_BOUND)
        self.assertIn("not published", ls["private_ingest"]["label"].lower())

        st, body = self._call(
            "POST", f"/api/live-sessions/{sid}/private-ingest/media",
            token=self.op_token,
            body={"content_base64": base64.b64encode(b"http-priv").decode()},
        )
        self.assertEqual(st, 200)
        self.assertEqual(body["live_session"]["private_ingest"]["private_ingest_state"], INGEST_RECEIVING)

        # Member denied — no session leak
        st, body = self._call(
            "POST", f"/api/live-sessions/{sid}/private-ingest",
            token=self.member_token,
            body={},
        )
        self.assertEqual(st, 403)
        self.assertEqual(body.get("code"), "operator_required")
        self.assertNotIn("live_session", body)

        st, body = self._call(
            "POST", f"/api/live-sessions/{sid}/private-ingest/media",
            token=self.member_token,
            body={"content_base64": base64.b64encode(b"x").decode()},
        )
        self.assertEqual(st, 403)

        # Flag off → 503
        os.environ[FLAG] = "false"
        st, body = self._call(
            "POST", f"/api/live-sessions/{sid}/private-ingest",
            token=self.op_token,
            body={},
        )
        self.assertEqual(st, 503)
        self.assertEqual(body.get("code"), "private_live_capture_disabled")
        os.environ[FLAG] = "true"

    def test_11_ui_labels_honest_private_ingest(self):
        req = request.Request(f"http://127.0.0.1:{self.port}/ops/private-capture")
        with request.urlopen(req, timeout=5) as resp:
            html = resp.read().decode()
            self.assertEqual(resp.status, 200)
        self.assertIn("Private capture session — Browser source not published", html)
        self.assertIn("Private ingest is never published", html)
        self.assertIn("No third-party live publish", html)
        req_js = request.Request(f"http://127.0.0.1:{self.port}/private_capture.js")
        with request.urlopen(req_js, timeout=5) as resp:
            js = resp.read().decode()
        self.assertIn("private-ingest", js)
        self.assertIn("getUserMedia", js)
        self.assertNotIn("cloudflare", js.lower())
        self.assertNotIn("restream", js.lower())
        self.assertNotIn("LIVE_PUBLIC", js)
        self.assertNotIn("/api/events/", js)


if __name__ == "__main__":
    unittest.main()
