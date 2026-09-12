"""G4-C — hook sports-verify on private capture frames only.

Isolated SQLite. Network-free. Proves: flag-off → 503; non-operator 403;
verify never flips LIVE_PUBLIC / distribution ENABLED; publish false always;
no provider provision / ControlPlane.transition(live); works with private
source without claiming public.
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

from backend.config import (  # noqa: E402
    Config,
    private_live_capture_enabled,
    sports_verify_enabled,
)
from backend.control_plane import (  # noqa: E402
    ConflictError,
    ControlPlane,
    ForbiddenError,
    SITE_ROUTES,
)
from backend.db import Database  # noqa: E402
from backend.live_sessions import (  # noqa: E402
    DISTRIBUTION_DISABLED,
    FeatureDisabledError,
    LiveSessionService,
    PRIVATE_SPORTS_VERIFY_LABEL,
    PROVIDER_NAME,
    PUBLIC_STATE_LIVE_PRIVATE,
    STATE_STOPPED,
)
from backend.seed import seed_if_empty  # noqa: E402
from backend.sports_check import sports_status_from_policy_decision  # noqa: E402
from threezone_ai.vision.types import (  # noqa: E402
    DECISION_ELIGIBLE,
    DECISION_HOLD,
    DECISION_REJECT,
)

FLAG_CAPTURE = "THREEZONE_PRIVATE_LIVE_CAPTURE_ENABLED"
FLAG_VERIFY = "THREEZONE_SPORTS_VERIFY_ENABLED"


def _clear_flags() -> None:
    os.environ.pop(FLAG_CAPTURE, None)
    os.environ.pop(FLAG_VERIFY, None)


def _enable_both() -> None:
    os.environ[FLAG_CAPTURE] = "true"
    os.environ[FLAG_VERIFY] = "true"


def _build(media_dir: str | None = None) -> tuple[ControlPlane, LiveSessionService, str]:
    cfg = Config(env="development", allowed_origins=["http://127.0.0.1:8000"])
    db = Database(":memory:")
    seed_if_empty(db)
    cp = ControlPlane(db, cfg)
    tmp = media_dir or tempfile.mkdtemp(prefix="g4c_media_")
    return cp, LiveSessionService(cp, media_dir=tmp), tmp


class PrivateSportsVerifyServiceTests(unittest.TestCase):
    def setUp(self):
        _enable_both()
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
        _clear_flags()

    def _session_with_frame(self, key: str, payload: bytes = b"private-frame"):
        s = self.svc.start(self.operator, {"idempotency_key": key})
        self.svc.bind_private_ingest(self.operator, s["live_session_id"])
        self.svc.receive_private_media(self.operator, s["live_session_id"], {
            "content_base64": base64.b64encode(payload).decode(),
        })
        return s

    def test_01_flag_off_private_capture_503(self):
        s = self._session_with_frame("g4c-off-cap")
        os.environ[FLAG_CAPTURE] = "false"
        self.assertFalse(private_live_capture_enabled())
        with self.assertRaises(FeatureDisabledError) as ctx:
            self.svc.run_private_sports_check(self.operator, s["live_session_id"])
        self.assertEqual(ctx.exception.code, "private_live_capture_disabled")
        self.assertEqual(ctx.exception.status, 503)

    def test_02_flag_off_sports_verify_503(self):
        s = self._session_with_frame("g4c-off-ver")
        os.environ[FLAG_VERIFY] = "false"
        self.assertFalse(sports_verify_enabled())
        self.assertTrue(private_live_capture_enabled())
        with self.assertRaises(FeatureDisabledError) as ctx:
            self.svc.run_private_sports_check(self.operator, s["live_session_id"])
        self.assertEqual(ctx.exception.code, "sports_verify_disabled")
        self.assertEqual(ctx.exception.status, 503)

    def test_03_non_operator_403(self):
        s = self._session_with_frame("g4c-mem")
        with self.assertRaises(ForbiddenError) as ctx:
            self.svc.run_private_sports_check(self.member, s["live_session_id"])
        self.assertEqual(ctx.exception.code, "operator_required")

    def test_04_verify_does_not_flip_public_or_distribution(self):
        s = self._session_with_frame("g4c-nopub")
        sid = s["live_session_id"]
        out = self.svc.run_private_sports_check(self.operator, sid, {
            "public_state": "LIVE_PUBLIC",
            "distribution_state": "ENABLED",
            "publish": True,
            "provider_stream_id": "cf_evil",
            "restream_event_id": "rst_evil",
        })
        session = out["live_session"]
        check = out["private_sports_check"]
        self.assertEqual(session["public_state"], PUBLIC_STATE_LIVE_PRIVATE)
        self.assertEqual(session["distribution_state"], DISTRIBUTION_DISABLED)
        self.assertEqual(session["provider_name"], PROVIDER_NAME)
        self.assertIsNone(session["provider_stream_id"])
        self.assertIsNone(session["restream_event_id"])
        self.assertFalse(check["publish"])
        self.assertFalse(session["private_sports_verify"]["publish"])
        self.assertEqual(check["public_state"], PUBLIC_STATE_LIVE_PRIVATE)
        self.assertEqual(check["distribution_state"], DISTRIBUTION_DISABLED)
        self.assertEqual(session["private_sports_verify"]["label"], PRIVATE_SPORTS_VERIFY_LABEL)
        self.assertIn("not publish", session["private_sports_verify"]["label"].lower())

    def test_05_publish_false_always_and_stores_result(self):
        s = self._session_with_frame("g4c-store")
        sid = s["live_session_id"]
        out = self.svc.run_private_sports_check(self.operator, sid)
        check = out["private_sports_check"]
        self.assertFalse(check["publish"])
        self.assertIsNotNone(check["decision"])
        self.assertIsNotNone(check["bundle_id"])
        self.assertEqual(check["source_mode"], "private_capture")
        self.assertTrue(str(check["private_asset_id"]).startswith("priv_asset_"))
        session = out["live_session"]
        verify = session["private_sports_verify"]
        self.assertEqual(verify["decision"], check["decision"])
        self.assertEqual(verify["bundle_id"], check["bundle_id"])
        self.assertFalse(verify["publish"])
        self.assertIsNotNone(verify["verified_at"])
        # sports_status honest from policy — never publish auth
        self.assertIn(
            session["sports_status"],
            {"HOLD", "REJECT_NON_SPORTS", "ELIGIBLE_FOR_RIGHTS_CHECK", "UNVERIFIED"},
        )
        # Private binary → private_capture scenario → hold/reject typically
        self.assertIn(check["decision"], {
            DECISION_HOLD, DECISION_REJECT, DECISION_ELIGIBLE,
        })
        row = self.cp.db.query_one(
            "SELECT private_verify_publish, public_state, distribution_state, "
            "provider_stream_id, restream_event_id FROM live_sessions "
            "WHERE live_session_id=?",
            (sid,),
        )
        self.assertEqual(int(row["private_verify_publish"] or 0), 0)
        self.assertEqual(row["public_state"], PUBLIC_STATE_LIVE_PRIVATE)
        self.assertEqual(row["distribution_state"], DISTRIBUTION_DISABLED)
        self.assertIsNone(row["provider_stream_id"])
        self.assertIsNone(row["restream_event_id"])

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
                        "idempotency_key": "g4c-bans",
                        "event_id": "evt_mw_basketball",
                    })
                    self.svc.bind_private_ingest(self.operator, s["live_session_id"])
                    self.svc.receive_private_media(self.operator, s["live_session_id"], {
                        "content_base64": base64.b64encode(b"abc").decode(),
                    })
                    out = self.svc.run_private_sports_check(
                        self.operator, s["live_session_id"]
                    )
                    self.assertFalse(out["private_sports_check"]["publish"])
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

    def test_07_works_with_private_source_without_claiming_public(self):
        s = self._session_with_frame("g4c-privsrc", b"rewind-private-bytes")
        sid = s["live_session_id"]
        out = self.svc.run_private_sports_check(self.operator, sid)
        check = out["private_sports_check"]
        self.assertEqual(check["source_mode"], "private_capture")
        self.assertTrue(check["source_asset_id"].startswith("asset:private:"))
        self.assertFalse(check["publish"])
        self.assertEqual(out["live_session"]["public_state"], PUBLIC_STATE_LIVE_PRIVATE)
        # Must not claim public rails (note text may mention LIVE_PUBLIC as a ban).
        self.assertNotEqual(out["live_session"]["public_state"], "LIVE_PUBLIC")
        self.assertNotEqual(check["public_state"], "LIVE_PUBLIC")
        self.assertEqual(check["distribution_state"], DISTRIBUTION_DISABLED)
        self.assertNotIn("PUBLICATION_PENDING", out["live_session"].get("session_state", ""))
        self.assertNotEqual(out["live_session"]["distribution_state"], "ENABLED")

    def test_08_eligible_offline_synthetic_still_not_publish(self):
        """Optional offline synthetic dry-run may be eligible — still not publish."""
        s = self._session_with_frame("g4c-synth")
        sid = s["live_session_id"]
        out = self.svc.run_private_sports_check(self.operator, sid, {
            "offline_synthetic_asset_id": "asset:synthetic:basketball-001",
        })
        check = out["private_sports_check"]
        self.assertEqual(check["source_mode"], "offline_synthetic")
        self.assertFalse(check["publish"])
        self.assertEqual(out["live_session"]["public_state"], PUBLIC_STATE_LIVE_PRIVATE)
        self.assertEqual(out["live_session"]["distribution_state"], DISTRIBUTION_DISABLED)
        # Eligible-style sports_status is NOT publish authorization
        if check["decision"] == DECISION_ELIGIBLE:
            self.assertEqual(
                out["live_session"]["sports_status"], "ELIGIBLE_FOR_RIGHTS_CHECK"
            )
        self.assertNotEqual(out["live_session"]["public_state"], "LIVE_PUBLIC")

    def test_09_no_private_frame_fails_closed(self):
        s = self.svc.start(self.operator, {"idempotency_key": "g4c-nofrm"})
        from backend.control_plane import ValidationError
        with self.assertRaises(ValidationError) as ctx:
            self.svc.run_private_sports_check(self.operator, s["live_session_id"])
        self.assertEqual(ctx.exception.code, "private_frame_required")

    def test_10_sports_status_mapper_honest(self):
        self.assertEqual(
            sports_status_from_policy_decision(DECISION_ELIGIBLE),
            "ELIGIBLE_FOR_RIGHTS_CHECK",
        )
        self.assertEqual(sports_status_from_policy_decision(DECISION_HOLD), "HOLD")
        self.assertEqual(
            sports_status_from_policy_decision(DECISION_REJECT), "REJECT_NON_SPORTS"
        )
        self.assertEqual(sports_status_from_policy_decision("weird"), "UNVERIFIED")

    def test_11_owner_allowed(self):
        s = self._session_with_frame("g4c-owner")
        out = self.svc.run_private_sports_check(self.owner, s["live_session_id"])
        self.assertFalse(out["private_sports_check"]["publish"])
        self.assertEqual(
            out["live_session"]["public_state"], PUBLIC_STATE_LIVE_PRIVATE
        )

    def test_12_schema_columns_present(self):
        from backend.db import SCHEMA, _postgres_schema
        for col in (
            "private_verify_decision",
            "private_verify_bundle_id",
            "private_verify_publish",
            "private_verify_lane",
        ):
            self.assertIn(col, SCHEMA)
            self.assertIn(col, _postgres_schema())


class PrivateSportsVerifyHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _enable_both()
        from backend.http_server import make_http_server

        cls._tmpdir = tempfile.mkdtemp(prefix="g4c_http_")
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
        _clear_flags()

    def setUp(self):
        _enable_both()

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
            with request.urlopen(req, timeout=15) as resp:
                return resp.status, json.loads(resp.read().decode())
        except error.HTTPError as exc:
            payload = exc.read().decode()
            try:
                parsed = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                parsed = {"raw": payload}
            return exc.code, parsed

    def _session_with_media(self, key: str):
        st, payload = self._call(
            "POST", "/api/live-sessions",
            token=self.op_token,
            body={"idempotency_key": key},
        )
        self.assertEqual(st, 201, payload)
        sid = payload["live_session"]["live_session_id"]
        st, _ = self._call(
            "POST", f"/api/live-sessions/{sid}/private-ingest",
            token=self.op_token, body={},
        )
        self.assertEqual(st, 200)
        st, _ = self._call(
            "POST", f"/api/live-sessions/{sid}/private-ingest/media",
            token=self.op_token,
            body={"content_base64": base64.b64encode(b"http-priv").decode()},
        )
        self.assertEqual(st, 200)
        return sid

    def test_20_http_flag_off_503(self):
        sid = self._session_with_media("http-g4c-off")
        os.environ[FLAG_VERIFY] = "false"
        st, body = self._call(
            "POST", f"/api/live-sessions/{sid}/private-sports-check",
            token=self.op_token, body={},
        )
        self.assertEqual(st, 503)
        self.assertEqual(body.get("code"), "sports_verify_disabled")

    def test_21_http_member_403(self):
        sid = self._session_with_media("http-g4c-mem")
        st, body = self._call(
            "POST", f"/api/live-sessions/{sid}/private-sports-check",
            token=self.member_token, body={},
        )
        self.assertEqual(st, 403)
        self.assertEqual(body.get("code"), "operator_required")

    def test_22_http_verify_publish_false_stays_private(self):
        sid = self._session_with_media("http-g4c-ok")
        st, body = self._call(
            "POST", f"/api/live-sessions/{sid}/private-sports-check",
            token=self.op_token,
            body={"public_state": "LIVE_PUBLIC", "publish": True},
        )
        self.assertEqual(st, 200, body)
        self.assertFalse(body["private_sports_check"]["publish"])
        ls = body["live_session"]
        self.assertEqual(ls["public_state"], PUBLIC_STATE_LIVE_PRIVATE)
        self.assertEqual(ls["distribution_state"], DISTRIBUTION_DISABLED)
        self.assertIsNone(ls["provider_stream_id"])
        self.assertIsNone(ls["restream_event_id"])
        self.assertFalse(ls["private_sports_verify"]["publish"])

    def test_23_ui_has_honest_button(self):
        req = request.Request(f"http://127.0.0.1:{self.port}/ops/private-capture")
        with request.urlopen(req, timeout=5) as resp:
            html = resp.read().decode()
        self.assertIn("sports-check-btn", html)
        self.assertIn("evidence only", html.lower())
        self.assertIn("not publish", html.lower())
        req_js = request.Request(f"http://127.0.0.1:{self.port}/private_capture.js")
        with request.urlopen(req_js, timeout=5) as resp:
            js = resp.read().decode()
        self.assertIn("/private-sports-check", js)

    def test_24_site_routes_catalog(self):
        paths = {r["path"] for r in SITE_ROUTES}
        self.assertIn("/api/live-sessions/{id}/private-sports-check", paths)


if __name__ == "__main__":
    unittest.main()
