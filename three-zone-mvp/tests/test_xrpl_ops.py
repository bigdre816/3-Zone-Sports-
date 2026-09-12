"""Operator XRPL account snapshot helpers."""

from __future__ import annotations

import unittest
from unittest import mock

from backend import xrpl_ops


class XrplOpsUnitTests(unittest.TestCase):
    def test_rejects_bad_address(self):
        with self.assertRaises(ValueError):
            xrpl_ops.validate_classic_address("not-an-address")

    def test_rejects_bad_network(self):
        with self.assertRaises(ValueError):
            xrpl_ops.normalize_network("devnet")

    def test_drops_to_xrp(self):
        self.assertEqual(xrpl_ops.drops_to_xrp("2500000"), "2.500000")

    def test_snapshot_shape_with_mocked_rpc(self):
        def fake_rpc(network, method, params, timeout=12.0):
            if method == "account_info":
                return {"account_data": {"Account": "rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe", "Balance": "1000000", "Sequence": 7, "OwnerCount": 0}}
            if method == "account_tx":
                return {"transactions": [{
                    "tx": {
                        "hash": "ABCD" * 16,
                        "TransactionType": "Payment",
                        "Account": "rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe",
                        "Destination": "rN7n7otQDd6FczFgLdlqtyMVea3zAjyTqF",
                        "Amount": "500000",
                        "ledger_index": 12,
                    },
                    "meta": {"TransactionResult": "tesSUCCESS"},
                    "validated": True,
                }]}
            raise AssertionError(method)

        with mock.patch.object(xrpl_ops, "_rpc", side_effect=fake_rpc):
            snap = xrpl_ops.account_snapshot("rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe", "testnet")
        self.assertEqual(snap["balance_xrp"], "1.000000")
        self.assertEqual(len(snap["transactions"]), 1)
        self.assertEqual(snap["transactions"][0]["transaction_type"], "Payment")
        self.assertNotIn("secret", snap)
        self.assertNotIn("seed", snap)
        self.assertNotIn("private_key", snap)


if __name__ == "__main__":
    unittest.main()
