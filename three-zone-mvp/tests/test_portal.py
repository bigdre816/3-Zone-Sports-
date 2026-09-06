import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.config import Config
from backend.control_plane import ControlPlane, ForbiddenError
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
        self.assertEqual(len(self.db.query("SELECT * FROM schedule_versions WHERE schedule_id=?", (first["schedule_id"],))), 2)

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


if __name__ == "__main__":
    unittest.main()
