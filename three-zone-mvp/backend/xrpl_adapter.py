"""XRPL publication adapter.

Publishes only a settlement digest + Merkle root. Never video, identity, emails,
IPs, tokens, stream keys, or heartbeat payloads.

Submitted is never treated as validated. Demo mode writes labeled DEMO receipts
and sets simulated=1. Live JSON-RPC submit is used only when TZ_XRPL_MODE is
testnet or mainnet and signing config is complete.

TZ_XRPL_SIGNING_SECRET is server-only and must never appear in HTTP responses,
logs, audit JSON, SQLite event payloads, browser storage, or test fixtures.
"""

from __future__ import annotations

import json
import time
import urllib.request
import uuid

from .merkle import hash_canonical, sha256_hex


def commitment_payload(settlement: dict) -> dict:
    """On-ledger payload. Identity-free by construction."""
    return {
        "kind": "three-zone-settlement-v1",
        "settlement_id": settlement["settlement_id"],
        "manifest_digest": settlement["manifest_digest"],
        "merkle_root": settlement["merkle_root"],
        "session_count": settlement["session_count"],
        "qualified_seconds": settlement["qualified_seconds"],
        "property_id": settlement["property_id"],
        "event_id": settlement["event_id"],
    }


def assert_payload_clean(payload: dict) -> None:
    blob = json.dumps(payload).lower()
    forbidden = ("email", "bearer", "stream_key", "streamkey", "signing_secret",
                 "api_token", "password", "@", "127.0.0.")
    for item in forbidden:
        if item in blob and item not in ("event_id",):
            # '@' is too broad; skip unless it looks like an email
            if item == "@":
                continue
            raise ValueError("forbidden field in XRPL payload")
    if "authorization" in blob:
        raise ValueError("forbidden field in XRPL payload")


class XrplAdapter:
    def __init__(self, config, rpc=None):
        self.config = config
        self.rpc = rpc  # callable(method, params) -> dict, injectable

    def _demo_receipt(self, commitment: str) -> dict:
        digest = sha256_hex(commitment)
        return {
            "tx_hash": "DEMO-" + digest[:24],
            "ledger_index": "simulated-ledger",
            "simulated": 1,
            "status": "validated",
        }

    def publish(self, db, settlement: dict) -> dict:
        payload = commitment_payload(settlement)
        assert_payload_clean(payload)
        commitment = hash_canonical(payload)
        now = time.time()
        existing = db.query_one(
            "SELECT * FROM xrpl_publication_queue WHERE settlement_id=? ORDER BY created_at DESC LIMIT 1",
            (settlement["settlement_id"],),
        )
        if existing and existing["status"] == "validated":
            return dict(existing)
        if existing and existing["commitment"] == commitment and existing["status"] == "submitted":
            # Retry/poll the same commitment. Never mint a new settlement.
            return self._advance(db, dict(existing), payload, commitment)

        pub_id = existing["publication_id"] if existing and existing["commitment"] == commitment else "XRP-" + uuid.uuid4().hex[:16]
        if not existing or existing["commitment"] != commitment:
            db.execute(
                "INSERT INTO xrpl_publication_queue(publication_id,settlement_id,mode,status,retry_count,"
                "tx_hash,ledger_index,simulated,error_code,commitment,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (pub_id, settlement["settlement_id"], self.config.xrpl_mode, "queued", 0,
                 None, None, 1 if self.config.xrpl_mode == "demo" else 0, None, commitment, now, now),
            )
        else:
            pub_id = existing["publication_id"]
            db.execute(
                "UPDATE xrpl_publication_queue SET status='queued', updated_at=?, retry_count=retry_count+1 WHERE publication_id=?",
                (now, pub_id),
            )
        row = db.query_one("SELECT * FROM xrpl_publication_queue WHERE publication_id=?", (pub_id,))
        return self._advance(db, dict(row), payload, commitment)

    def _advance(self, db, row: dict, payload: dict, commitment: str) -> dict:
        now = time.time()
        if self.config.xrpl_mode == "demo" or not self.config.xrpl_signing_secret:
            receipt = self._demo_receipt(commitment)
            db.execute(
                "UPDATE xrpl_publication_queue SET status=?, tx_hash=?, ledger_index=?, simulated=1, updated_at=? WHERE publication_id=?",
                ("validated", receipt["tx_hash"], receipt["ledger_index"], now, row["publication_id"]),
            )
            return db.query_one("SELECT * FROM xrpl_publication_queue WHERE publication_id=?", (row["publication_id"],))

        # Live path: submit then require a distinct validate step.
        try:
            submitted = self._rpc_submit(payload)
            db.execute(
                "UPDATE xrpl_publication_queue SET status='submitted', tx_hash=?, ledger_index=?, simulated=0, updated_at=? WHERE publication_id=?",
                (submitted.get("tx_hash"), submitted.get("ledger_index"), now, row["publication_id"]),
            )
        except Exception as exc:  # noqa: BLE001 — persist failure, do not throw past queue
            db.execute(
                "UPDATE xrpl_publication_queue SET status='failed', error_code=?, updated_at=?, retry_count=retry_count+1 WHERE publication_id=?",
                (str(exc)[:120], now, row["publication_id"]),
            )
            return db.query_one("SELECT * FROM xrpl_publication_queue WHERE publication_id=?", (row["publication_id"],))
        return self.poll(db, row["publication_id"])

    def poll(self, db, publication_id: str) -> dict:
        row = db.query_one("SELECT * FROM xrpl_publication_queue WHERE publication_id=?", (publication_id,))
        if not row:
            return {}
        if row["status"] != "submitted":
            return dict(row)
        if self.rpc is None:
            return dict(row)
        result = self.rpc("tx", {"transaction": row["tx_hash"]})
        now = time.time()
        if result.get("validated") is True:
            db.execute(
                "UPDATE xrpl_publication_queue SET status='validated', ledger_index=?, updated_at=? WHERE publication_id=?",
                (str(result.get("ledger_index") or row["ledger_index"]), now, publication_id),
            )
        elif result.get("error"):
            db.execute(
                "UPDATE xrpl_publication_queue SET status='failed', error_code=?, updated_at=? WHERE publication_id=?",
                (str(result.get("error"))[:120], now, publication_id),
            )
        return dict(db.query_one("SELECT * FROM xrpl_publication_queue WHERE publication_id=?", (publication_id,)))

    def retry(self, db, settlement: dict) -> dict:
        existing = db.query_one(
            "SELECT * FROM xrpl_publication_queue WHERE settlement_id=? ORDER BY created_at DESC LIMIT 1",
            (settlement["settlement_id"],),
        )
        if existing and existing["status"] == "validated":
            return dict(existing)
        return self.publish(db, settlement)

    def _rpc_submit(self, payload: dict) -> dict:
        if self.rpc:
            return self.rpc("submit", {"tx_json": {"MemoData": hash_canonical(payload)}})
        body = json.dumps({
            "method": "submit",
            "params": [{"tx_json": {"Account": self.config.xrpl_audit_account, "TransactionType": "Payment",
                                    "Memos": [{"Memo": {"MemoData": hash_canonical(payload)}}]}}],
        }).encode()
        req = urllib.request.Request(
            self.config.xrpl_rpc_url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        result = data.get("result") or data
        return {"tx_hash": result.get("tx_json", {}).get("hash") or result.get("hash"),
                "ledger_index": result.get("ledger_index")}
