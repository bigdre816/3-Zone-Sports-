import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.config import Config
from backend.control_plane import ControlPlane, ForbiddenError, AuthError, ValidationError, ConflictError
from backend.db import Database
from backend.portal import PortalService
from backend.seed import seed_if_empty


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        seed_if_empty(self.db)
        self.cp = ControlPlane(self.db, Config(env="demo", allowed_origins=["http://localhost"]))
        self.portal = PortalService(self.cp)
        self.member = self.cp.get_user("demo-viewer")
        self.operator = self.cp.get_user("demo-owner")

    def session(self):
        return self.portal.complete_auth("demo-viewer")

    def test_verified_member_gets_server_session_and_live_lease(self):
        session = self.session()
        result = self.portal.playback(session["session_id"], "evt_mw_basketball")
        self.assertTrue(result["allow"])
        self.assertTrue(self.cp.validate_lease("evt_mw_basketball", result["lease_token"])["valid"])

    def test_unverified_member_is_denied(self):
        with self.assertRaises(ForbiddenError):
            self.portal.session("not-a-session")

    def test_expired_or_revoked_verification_denies_playback(self):
        session = self.session()
        self.db.execute("UPDATE member_verifications SET status='REVOKED' WHERE verification_id=?",
                        (session["verification"]["verification_id"],))
        with self.assertRaises(ForbiddenError):
            self.portal.playback(session["session_id"], "evt_mw_basketball")

    def test_revoked_rights_rejects_future_media(self):
        session = self.session()
        lease = self.portal.playback(session["session_id"], "evt_mw_basketball")
        self.cp.revoke_rights("evt_mw_basketball", self.operator, "stop")
        self.assertFalse(self.cp.validate_lease("evt_mw_basketball", lease["lease_token"])["valid"])

    def test_schedule_upload_preserves_prior_version_and_rejects_bad_rows(self):
        self.portal._ensure_catalog()
        bad = b"school,team,sport,level,opponent,date,start time,location,home/away,season\nLincoln High,Lincoln Freshman Basketball,basketball,freshman,Central,,19:00,Gym,HOME,2026\n"
        self.assertFalse(self.portal.upload_schedule(self.operator, "bad.csv", bad)["accepted"])
        good = b"school,team,sport,level,opponent,date,start time,location,home/away,season\nLincoln High,Lincoln Freshman Basketball,basketball,freshman,Central,2026-12-01,19:00,Gym,HOME,2026\n"
        first = self.portal.upload_schedule(self.operator, "good.csv", good)
        second = self.portal.upload_schedule(self.operator, "corrected.csv", good)
        self.assertTrue(first["accepted"]); self.assertEqual(second["version"], first["version"] + 1)
        self.assertEqual(len(self.db.query("SELECT * FROM schedule_versions WHERE schedule_id=?", (first["schedule_id"],))), second["version"])

    def test_schedule_upload_seeds_catalog_for_control_plane_import(self):
        sample = b"school,team,sport,level,opponent,date,start time,location,home/away,season\nLincoln High,Lincoln Freshman Basketball,basketball,freshman,West,2026-11-12,19:00,Lincoln Gym,HOME,2026\n"
        result = self.portal.upload_schedule(self.operator, "lincoln-2026.csv", sample)
        self.assertTrue(result["accepted"])
        self.assertFalse(result.get("errors"))

    def test_audit_persists_before_simulated_xrpl_receipt(self):
        session = self.session()
        self.portal.playback(session["session_id"], "evt_mw_basketball")
        audit = self.db.query_one("SELECT * FROM audit_events WHERE event_type='lease.issued'")
        self.assertIsNotNone(audit)
        self.portal.publish_pending()
        publication = self.db.query_one("SELECT * FROM xrpl_publications WHERE audit_event_id=?", (audit["event_id"],))
        self.assertEqual(publication["status"], "VALIDATED")
        self.assertTrue(publication["simulated"])

    def test_public_configuration_never_exposes_xrpl_secret(self):
        config = Config(env="demo", xrpl_signing_secret="do-not-show", allowed_origins=["http://localhost"])
        self.assertNotIn("do-not-show", str(config.public_config()))

    def test_catalog_seed_survives_concurrent_first_load(self):
        import threading
        errors = []

        def load():
            try:
                self.portal.live(self.member)
                self.portal.schedules(self.member)
                self.portal.archives(self.member)
            except Exception as exc:  # noqa: BLE001 - collect any worker failure
                errors.append(exc)

        threads = [threading.Thread(target=load) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertGreaterEqual(len(self.portal.live(self.member)), 1)
        self.assertGreaterEqual(len(self.portal.schedules(self.member)), 1)
        self.assertGreaterEqual(len(self.portal.archives(self.member)), 1)

    def test_password_login_all_seeded_roles(self):
        from backend.config import DEMO_SEED_PASSWORDS
        for username, home in (("demo-viewer", "/"), ("demo-worker", "/ops"), ("demo-owner", "/ops")):
            result = self.cp.password_login(username, DEMO_SEED_PASSWORDS[username])
            self.assertEqual(result["home"], home)
            self.assertEqual(result["user"]["user_id"], username)
            self.assertTrue(result["session_token"])

    def test_password_login_rejects_bad_password(self):
        with self.assertRaises(AuthError) as ctx:
            self.cp.password_login("demo-owner", "wrong-password")
        self.assertEqual(ctx.exception.code, "invalid_credentials")

    def test_register_viewer_can_play_and_cannot_be_staff(self):
        created = self.cp.register_viewer("pat-member", "password123", "Pat")
        self.assertEqual(created["user"]["role"], "viewer")
        self.assertEqual(created["home"], "/")
        session = self.portal.complete_auth("pat-member")
        lease = self.portal.playback(session["session_id"], "evt_mw_basketball")
        self.assertTrue(lease["allow"])
        with self.assertRaises(ValidationError):
            self.cp.register_viewer("demo-owner", "password123", "Nope")
        with self.assertRaises(ConflictError):
            self.cp.register_viewer("pat-member", "password123", "Pat")

    def test_control_plane_app_js_is_preserved(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "backend", "static", "app.js"), encoding="utf-8") as handle:
            app_js = handle.read()
        self.assertIn("async function revokeRights()", app_js)
        self.assertIn("async function loadInventory()", app_js)
        self.assertIn("async function loadMastery()", app_js)
        self.assertIn('querySelectorAll("#app [data-pane]")', app_js)
        self.assertIn("POST", app_js)
        self.assertGreater(len(app_js.splitlines()), 500)


if __name__ == "__main__":
    unittest.main()
