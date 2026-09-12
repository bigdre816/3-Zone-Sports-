"""G4-B — optional short private rewind buffer (bounded; NOT full DVR).

Isolated SQLite. Network-free. Proves: flag-off; non-operator denied;
buffer evicts beyond bound; cannot force LIVE_PUBLIC/Restream; no provider
provision / ControlPlane.transition(live); clear on stop.
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
    INGEST_RECEIVING,
    LiveSessionService,
    PRIVATE_REWIND_LABEL,
    PRIVATE_REWIND_MAX_CHUNKS,
    PRIVATE_REWIND_MAX_SECONDS,
    PRIVATE_REWIND_MAX_TOTAL_BYTES,
    PROVIDER_NAME,
    PUBLIC_STATE_LIVE_PRIVATE,
    STATE_STOPPED,
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
    tmp = media_dir or tempfile.mkdtemp(prefix="g4b_media_")
    return cp, LiveSessionService(cp, media_dir=tmp), tmp


class PrivateRewindServiceTests(unittest.TestCase):
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

    def _session_with_ingest(self, key: str):
        s = self.svc.start(self.operator, {"idempotency_key": key})
        self.svc.bind_private_ingest(self.operator, s["live_session_id"])
        return s

    def _push(self, sid: str, payload: bytes):
        return self.svc.receive_private_media(self.operator, sid, {
            "content_base64": base64.b64encode(payload).decode(),
        })

    def test_01_flag_off_blocks_rewind_ops(self):
        s = self._session_with_ingest("g4b-off")
        self._push(s["live_session_id"], b"frame-a")
        os.environ[FLAG] = "false"
        self.assertFalse(private_live_capture_enabled())
        with self.assertRaises(FeatureDisabledError) as ctx:
            self.svc.list_private_rewind(self.operator, s["live_session_id"])
        self.assertEqual(ctx.exception.code, "private_live_capture_disabled")
        with self.assertRaises(FeatureDisabledError):
            self.svc.get_private_rewind_latest(self.operator, s["live_session_id"])
        with self.assertRaises(FeatureDisabledError):
            self._push(s["live_session_id"], b"frame-b")

    def test_02_non_operator_denied(self):
        s = self._session_with_ingest("g4b-mem")
        self._push(s["live_session_id"], b"x")
        with self.assertRaises(ForbiddenError) as ctx:
            self.svc.list_private_rewind(self.member, s["live_session_id"])
        self.assertEqual(ctx.exception.code, "operator_required")
        with self.assertRaises(ForbiddenError):
            self.svc.get_private_rewind_latest(self.member, s["live_session_id"])

    def test_03_buffer_evicts_beyond_chunk_bound(self):
        """Not unbounded DVR — chunk count bound evicts oldest."""
        s = self._session_with_ingest("g4b-evict")
        sid = s["live_session_id"]
        # Push MAX+5 tiny chunks; only MAX should remain.
        for i in range(PRIVATE_REWIND_MAX_CHUNKS + 5):
            self._push(sid, f"c{i}".encode())
        listed = self.svc.list_private_rewind(self.operator, sid)
        self.assertEqual(listed["chunk_count"], PRIVATE_REWIND_MAX_CHUNKS)
        self.assertLessEqual(len(listed["chunks"]), PRIVATE_REWIND_MAX_CHUNKS)
        self.assertFalse(listed["is_dvr"])
        self.assertEqual(listed["label"], PRIVATE_REWIND_LABEL)
        self.assertIn("not DVR", listed["label"])
        self.assertEqual(listed["public_state"], PUBLIC_STATE_LIVE_PRIVATE)
        self.assertEqual(listed["distribution_state"], DISTRIBUTION_DISABLED)
        # Oldest of the overflow batch should be gone.
        hashes = {c["chunk_id"] for c in listed["chunks"]}
        self.assertEqual(len(hashes), PRIVATE_REWIND_MAX_CHUNKS)
        session = self.svc.get(self.operator, sid)
        self.assertEqual(session["private_rewind"]["chunk_count"], PRIVATE_REWIND_MAX_CHUNKS)
        self.assertFalse(session["private_rewind"]["is_dvr"])

    def test_04_buffer_evicts_beyond_time_bound(self):
        s = self._session_with_ingest("g4b-time")
        sid = s["live_session_id"]
        t0 = 1_700_000_000.0
        with mock.patch("backend.live_sessions.now", return_value=t0):
            self._push(sid, b"old-chunk")
        # Advance past max window.
        with mock.patch(
            "backend.live_sessions.now",
            return_value=t0 + PRIVATE_REWIND_MAX_SECONDS + 5,
        ):
            self._push(sid, b"new-chunk")
            listed = self.svc.list_private_rewind(self.operator, sid)
        self.assertEqual(listed["chunk_count"], 1)
        self.assertEqual(
            listed["chunks"][0]["source_hash"],
            __import__("hashlib").sha256(b"new-chunk").hexdigest(),
        )

    def test_05_cannot_force_live_public_or_restream(self):
        s = self._session_with_ingest("g4b-public")
        sid = s["live_session_id"]
        out = self.svc.receive_private_media(self.operator, sid, {
            "content_base64": base64.b64encode(b"priv").decode(),
            "public_state": "LIVE_PUBLIC",
            "distribution_state": "ENABLED",
            "provider_name": "restream",
            "provider_stream_id": "cf_public",
            "restream_event_id": "rst_evil",
            "is_dvr": True,
            "private_rewind": {"is_dvr": True},
        })
        self.assertEqual(out["public_state"], PUBLIC_STATE_LIVE_PRIVATE)
        self.assertEqual(out["distribution_state"], DISTRIBUTION_DISABLED)
        self.assertEqual(out["provider_name"], PROVIDER_NAME)
        self.assertIsNone(out["provider_stream_id"])
        self.assertIsNone(out["restream_event_id"])
        self.assertFalse(out["private_rewind"]["is_dvr"])
        listed = self.svc.list_private_rewind(self.operator, sid)
        self.assertEqual(listed["public_state"], PUBLIC_STATE_LIVE_PRIVATE)
        self.assertEqual(listed["distribution_state"], DISTRIBUTION_DISABLED)
        self.assertIsNone(listed["provider_stream_id"])
        self.assertIsNone(listed["restream_event_id"])
        self.assertFalse(listed["is_dvr"])
        self.assertFalse(listed["published"])

    def test_06_no_provider_provision_or_transition_live(self):
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
                        "idempotency_key": "g4b-bans",
                        "event_id": "evt_mw_basketball",
                    })
                    self.svc.bind_private_ingest(self.operator, s["live_session_id"])
                    self._push(s["live_session_id"], b"abc")
                    self.svc.list_private_rewind(self.operator, s["live_session_id"])
                    self.svc.get_private_rewind_latest(self.operator, s["live_session_id"], {
                        "include_content": True,
                    })
                    self.svc.stop(self.operator, s["live_session_id"])

        self.assertEqual(provision_calls, [])
        self.assertEqual(transition_calls, [])
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

    def test_07_clear_on_stop(self):
        s = self._session_with_ingest("g4b-clear")
        sid = s["live_session_id"]
        self._push(sid, b"keep-me-briefly")
        listed = self.svc.list_private_rewind(self.operator, sid)
        self.assertEqual(listed["chunk_count"], 1)
        out = self.svc.stop(self.operator, sid, {"reason": "done"})
        self.assertEqual(out["session_state"], STATE_STOPPED)
        self.assertEqual(out["private_rewind"]["chunk_count"], 0)
        self.assertEqual(out["public_state"], PUBLIC_STATE_LIVE_PRIVATE)
        self.assertEqual(out["distribution_state"], DISTRIBUTION_DISABLED)
        listed2 = self.svc.list_private_rewind(self.operator, sid)
        self.assertEqual(listed2["chunk_count"], 0)
        latest = self.svc.get_private_rewind_latest(self.operator, sid)
        self.assertIsNone(latest["chunk"])
        # DB empty for session
        n = self.cp.db.query_one(
            "SELECT COUNT(*) AS c FROM private_rewind_chunks WHERE live_session_id=?",
            (sid,),
        )["c"]
        self.assertEqual(n, 0)

    def test_08_latest_chunk_and_constants_documented(self):
        self.assertGreaterEqual(PRIVATE_REWIND_MAX_SECONDS, 15)
        self.assertLessEqual(PRIVATE_REWIND_MAX_SECONDS, 60)
        self.assertGreaterEqual(PRIVATE_REWIND_MAX_CHUNKS, 1)
        self.assertGreater(PRIVATE_REWIND_MAX_TOTAL_BYTES, 0)
        s = self._session_with_ingest("g4b-latest")
        sid = s["live_session_id"]
        payload = b"latest-private-frame"
        self._push(sid, payload)
        latest = self.svc.get_private_rewind_latest(self.operator, sid, {
            "include_content": True,
            "public_state": "LIVE_PUBLIC",
            "is_dvr": True,
        })
        self.assertFalse(latest["is_dvr"])
        self.assertEqual(latest["public_state"], PUBLIC_STATE_LIVE_PRIVATE)
        self.assertIsNotNone(latest["chunk"])
        self.assertEqual(
            base64.b64decode(latest["chunk"]["content_base64"]),
            payload,
        )
        self.assertEqual(latest["label"], PRIVATE_REWIND_LABEL)

    def test_09_schema_private_rewind_table(self):
        rows = self.cp.db.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='private_rewind_chunks'"
        )
        self.assertTrue(rows)
        from backend.db import SCHEMA, _postgres_schema
        self.assertIn("private_rewind_chunks", SCHEMA)
        self.assertIn("private_rewind_chunks", _postgres_schema())


class PrivateRewindHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ[FLAG] = "true"
        from backend.http_server import make_http_server

        cls._tmpdir = tempfile.mkdtemp(prefix="g4b_http_")
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

    def test_10_http_rewind_member_denied_flag_off_clear(self):
        st, payload = self._call(
            "POST", "/api/live-sessions",
            token=self.op_token,
            body={"idempotency_key": "http-g4b"},
        )
        self.assertEqual(st, 201)
        sid = payload["live_session"]["live_session_id"]

        st, body = self._call(
            "POST", f"/api/live-sessions/{sid}/private-ingest",
            token=self.op_token,
            body={},
        )
        self.assertEqual(st, 200)

        st, body = self._call(
            "POST", f"/api/live-sessions/{sid}/private-ingest/media",
            token=self.op_token,
            body={"content_base64": base64.b64encode(b"http-rw").decode()},
        )
        self.assertEqual(st, 200)
        self.assertEqual(
            body["live_session"]["private_ingest"]["private_ingest_state"],
            INGEST_RECEIVING,
        )
        self.assertGreaterEqual(body["live_session"]["private_rewind"]["chunk_count"], 1)
        self.assertFalse(body["live_session"]["private_rewind"]["is_dvr"])

        st, body = self._call(
            "GET", f"/api/live-sessions/{sid}/private-rewind",
            token=self.op_token,
        )
        self.assertEqual(st, 200)
        rw = body["private_rewind"]
        self.assertEqual(rw["public_state"], "LIVE_PRIVATE")
        self.assertEqual(rw["distribution_state"], "DISABLED")
        self.assertFalse(rw["is_dvr"])
        self.assertIn("not DVR", rw["label"])
        self.assertGreaterEqual(rw["chunk_count"], 1)

        st, body = self._call(
            "GET", f"/api/live-sessions/{sid}/private-rewind/latest?include_content=true",
            token=self.op_token,
        )
        self.assertEqual(st, 200)
        self.assertIsNotNone(body["private_rewind_latest"]["chunk"])
        self.assertEqual(
            base64.b64decode(body["private_rewind_latest"]["chunk"]["content_base64"]),
            b"http-rw",
        )

        # Member denied
        st, body = self._call(
            "GET", f"/api/live-sessions/{sid}/private-rewind",
            token=self.member_token,
        )
        self.assertEqual(st, 403)
        self.assertEqual(body.get("code"), "operator_required")
        self.assertNotIn("private_rewind", body)

        # Flag off
        os.environ[FLAG] = "false"
        st, body = self._call(
            "GET", f"/api/live-sessions/{sid}/private-rewind",
            token=self.op_token,
        )
        self.assertEqual(st, 503)
        self.assertEqual(body.get("code"), "private_live_capture_disabled")
        os.environ[FLAG] = "true"

        # Stop clears
        st, body = self._call(
            "POST", f"/api/live-sessions/{sid}/stop",
            token=self.op_token,
            body={"reason": "http-done"},
        )
        self.assertEqual(st, 200)
        self.assertEqual(body["live_session"]["private_rewind"]["chunk_count"], 0)

        st, body = self._call(
            "GET", f"/api/live-sessions/{sid}/private-rewind",
            token=self.op_token,
        )
        self.assertEqual(st, 200)
        self.assertEqual(body["private_rewind"]["chunk_count"], 0)

    def test_11_ui_mentions_not_dvr(self):
        req = request.Request(f"http://127.0.0.1:{self.port}/ops/private-capture")
        with request.urlopen(req, timeout=5) as resp:
            html = resp.read().decode()
            self.assertEqual(resp.status, 200)
        self.assertIn("not DVR", html)
        req_js = request.Request(f"http://127.0.0.1:{self.port}/private_capture.js")
        with request.urlopen(req_js, timeout=5) as resp:
            js = resp.read().decode()
        self.assertIn("private-rewind", js)
        self.assertNotIn("cloudflare", js.lower())
        self.assertNotIn("restream", js.lower())
        self.assertNotIn("LIVE_PUBLIC", js)


if __name__ == "__main__":
    unittest.main()
