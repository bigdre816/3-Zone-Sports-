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



    def test_set_signing_account_binds_classic_address(self):
        svc = build()
        profile = svc.set_signing_account("rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe", "testnet")
        self.assertEqual(profile["account"], "rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe")
        self.assertEqual(profile["network"], "testnet")
        self.assertEqual(profile["status"], "CONFIGURED")
        health = svc.health()
        self.assertEqual(health["xrpl_mode"], "simulation")
        self.assertTrue(health["wallet_signed_publication_supported"])
        self.assertIn("honesty", health)
        self.assertIn("treasure", health["honesty"])

    def test_set_signing_account_rejects_bad_address(self):
        with self.assertRaisesRegex(ValueError, "invalid"):
            build().set_signing_account("not-an-address", "testnet")

    def test_confirm_wallet_publication_stores_receipt(self):
        svc = build()
        svc.set_signing_account("rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe", "testnet")
        created = svc.create_event(event(event_id="AUD-WALLET-1", event_type="evidence.manifest.created",
                                         payload={"purpose": "ops_wallet_test_publish"}))
        verification = svc.verify(created["event_id"])
        self.assertEqual(verification["verification_status"], "VERIFIED")
        request = svc.request_publication(created["event_id"], verification["verification_id"])
        tx_hash = "A1B2C3D4" * 8
        result = svc.confirm_wallet_publication(
            request["request_id"],
            tx_hash=tx_hash,
            account="rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe",
            network="testnet",
        )
        self.assertEqual(result["transaction_hash"], tx_hash)
        self.assertEqual(result["publication"]["status"], "VALIDATED")
        receipts = svc.list_receipts()
        self.assertTrue(any(r["transaction_hash"] == tx_hash and r["status"] == "VALIDATED" for r in receipts))

    def test_confirm_wallet_publication_rejects_account_mismatch(self):
        svc = build()
        svc.set_signing_account("rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe", "testnet")
        created = svc.create_event(event(event_id="AUD-WALLET-2", event_type="evidence.manifest.created",
                                         payload={"purpose": "ops_wallet_test_publish"}))
        verification = svc.verify(created["event_id"])
        request = svc.request_publication(created["event_id"], verification["verification_id"])
        with self.assertRaisesRegex(ValueError, "does not match"):
            svc.confirm_wallet_publication(
                request["request_id"],
                tx_hash="DEADBEEF" * 8,
                account="rN7n7otQDd6FczFgLdlqtyMVea3zAjyTqF",
                network="testnet",
            )


if __name__ == "__main__":
    unittest.main()
