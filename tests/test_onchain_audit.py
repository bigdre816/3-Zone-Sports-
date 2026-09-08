import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from moten_audit.config import Config
from moten_audit.db import Database
from moten_audit.service import AuditService, canonicalize, hash_canonical_audit_event


def build():
    cfg = Config("development", ":memory:", "simulation", "testnet", "", None, "test-profile", "simulation")
    return AuditService(Database(":memory:"), cfg)


def event(event_id="AUD-1", **extra):
    value = {
        "event_id": event_id, "event_type": "research.question.created", "organization_id": "MOTEN_IP",
        "source_system": "moten-control-plane", "object_id": "RQ-1", "object_version": "v1",
        "occurred_at": "2026-09-06T10:00:00Z", "actor_type": "human", "actor_id": "andre",
        "actor_role": "IP Steward", "action": "create", "payload": {"title": "Test"},
    }
    value.update(extra)
    return value


class AuditTests(unittest.TestCase):
    def test_canonicalization_is_deterministic(self):
        self.assertEqual(canonicalize({"b": None, "a": 1}), canonicalize({"a": 1, "b": None}))
        one, two = event(), event()
        one["recorded_at"] = two["recorded_at"] = "2026-09-06T10:00:00Z"
        self.assertEqual(hash_canonical_audit_event(one), hash_canonical_audit_event(two))

    def test_changed_version_changes_hash(self):
        svc = build()
        first = svc.create_event(event())
        second = svc.create_event(event("AUD-2", object_version="v2"))
        self.assertNotEqual(first["canonical_event_hash"], second["canonical_event_hash"])

    def test_secret_payload_is_held(self):
        svc = build()
        created = svc.create_event(event(payload={"seed": "not-stored"}))
        verification = svc.verify(created["event_id"])
        self.assertEqual(verification["verification_status"], "HELD")
        self.assertFalse(verification["eligible_for_onchain"])

    def test_unknown_schema_event_is_rejected_on_record(self):
        with self.assertRaisesRegex(ValueError, "unknown"):
            build().create_event(event(event_type="unregistered.event"))

    def test_lineage_must_match_preserved_event(self):
        svc = build()
        first = svc.create_event(event())
        second = svc.create_event(event("AUD-2", previous_event_id=first["event_id"],
                                        previous_event_hash=first["canonical_event_hash"]))
        self.assertEqual(second["previous_event_id"], first["event_id"])
        with self.assertRaisesRegex(ValueError, "lineage"):
            svc.create_event(event("AUD-3", previous_event_id="AUD-1", previous_event_hash="wrong"))

    def test_verification_then_simulated_receipt(self):
        svc = build()
        created = svc.create_event(event())
        verification = svc.verify(created["event_id"])
        request = svc.request_publication(created["event_id"], verification["verification_id"])
        result = svc.publish(request["request_id"])
        self.assertEqual(result["status"], "SIMULATED")
        receipt = svc.receipts(created["event_id"])[0]
        self.assertEqual(receipt["status"], "SIMULATED")
        self.assertIsNone(receipt["transaction_hash"])

    def test_held_verification_never_publishes(self):
        svc = build()
        created = svc.create_event(event(payload={"private_key": "blocked"}))
        verification = svc.verify(created["event_id"])
        with self.assertRaisesRegex(ValueError, "unverified"):
            svc.request_publication(created["event_id"], verification["verification_id"])

    def test_duplicate_prevention(self):
        svc = build()
        created = svc.create_event(event())
        verification = svc.verify(created["event_id"])
        first = svc.request_publication(created["event_id"], verification["verification_id"])
        second = svc.request_publication(created["event_id"], verification["verification_id"])
        self.assertEqual(first["request_id"], second["request_id"])

    def test_ai_cannot_request_publication(self):
        svc = build()
        created = svc.create_event(event())
        verification = svc.verify(created["event_id"])
        with self.assertRaises(PermissionError):
            svc.request_publication(created["event_id"], verification["verification_id"], "AI gateway")

    def test_reconciliation_clean_for_simulation(self):
        self.assertEqual(build().reconcile()["status"], "CLEAN")

    def test_browser_has_no_xrpl_secret_reference(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "index.html"), encoding="utf-8") as page:
            self.assertNotIn("MOTEN_XRPL_SECRET", page.read())


if __name__ == "__main__":
    unittest.main()
