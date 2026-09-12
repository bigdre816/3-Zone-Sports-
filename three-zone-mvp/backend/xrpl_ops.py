"""Operator XRPL read helpers for /ops wallet pane (secret-free).

Uses public JSON-RPC only. Never accepts or returns seeds/secrets.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

_CLASSIC_ADDR = re.compile(r"^r[1-9A-HJ-NP-Za-km-z]{24,34}$")

_NETWORKS = {
    "testnet": "https://s.altnet.rippletest.net:51234/",
    "mainnet": "https://xrplcluster.com/",
}


def normalize_network(network: str | None) -> str:
    name = (network or "testnet").strip().lower()
    if name not in _NETWORKS:
        raise ValueError("network must be testnet or mainnet")
    return name


def validate_classic_address(address: str) -> str:
    addr = (address or "").strip()
    if not _CLASSIC_ADDR.fullmatch(addr):
        raise ValueError("invalid XRPL classic address")
    return addr


def _rpc(network: str, method: str, params: list[Any], *, timeout: float = 12.0) -> dict:
    url = _NETWORKS[network]
    body = json.dumps({"method": method, "params": params}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"xrpl_http_{exc.code}:{detail}") from exc
    except Exception as exc:  # noqa: BLE001 — surface as operator-safe error
        raise RuntimeError(f"xrpl_unreachable:{type(exc).__name__}") from exc
    if "result" not in payload:
        raise RuntimeError("xrpl_bad_response")
    result = payload["result"]
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(f"xrpl_error:{result.get('error')}")
    return result if isinstance(result, dict) else {"value": result}


def drops_to_xrp(drops: str | int | float | None) -> str | None:
    if drops is None or drops == "":
        return None
    try:
        value = int(str(drops))
    except ValueError:
        return None
    whole = value // 1_000_000
    frac = abs(value) % 1_000_000
    return f"{whole}.{frac:06d}"


def account_snapshot(address: str, network: str = "testnet", *, tx_limit: int = 50) -> dict:
    """Balance + recent transactions for an operator-connected classic address."""
    network = normalize_network(network)
    address = validate_classic_address(address)
    limit = max(1, min(int(tx_limit or 50), 100))

    account_data = {}
    balance_drops = None
    account_error = None
    try:
        info = _rpc(
            network,
            "account_info",
            [{"account": address, "ledger_index": "validated", "queue": True}],
        )
        account_data = info.get("account_data") or {}
        balance_drops = account_data.get("Balance")
    except RuntimeError as exc:
        account_error = str(exc)

    tx_error = None
    try:
        tx_result = _rpc(
            network,
            "account_tx",
            [{
                "account": address,
                "ledger_index_min": -1,
                "ledger_index_max": -1,
                "binary": False,
                "forward": False,
                "limit": limit,
            }],
        )
        tx_rows = tx_result.get("transactions") or []
    except RuntimeError as exc:
        tx_rows = []
        msg = str(exc)
        if "actNotFound" not in msg and "accountNotFound" not in msg:
            tx_error = msg

    transactions = []
    for row in tx_rows:
        tx = row.get("tx") or row.get("tx_json") or {}
        meta = row.get("meta") or {}
        transactions.append({
            "hash": tx.get("hash") or row.get("hash"),
            "ledger_index": tx.get("ledger_index") or row.get("ledger_index"),
            "transaction_type": tx.get("TransactionType"),
            "account": tx.get("Account"),
            "destination": tx.get("Destination"),
            "amount_drops": (
                tx.get("Amount") if isinstance(tx.get("Amount"), (str, int)) else None
            ),
            "amount_xrp": drops_to_xrp(tx.get("Amount") if isinstance(tx.get("Amount"), (str, int)) else None),
            "result": meta.get("TransactionResult") if isinstance(meta, dict) else None,
            "date": tx.get("date"),
            "validated": bool(row.get("validated", True)),
        })

    return {
        "network": network,
        "rpc": _NETWORKS[network],
        "address": address,
        "account_found": bool(account_data),
        "account_error": account_error,
        "sequence": account_data.get("Sequence"),
        "owner_count": account_data.get("OwnerCount"),
        "balance_drops": balance_drops,
        "balance_xrp": drops_to_xrp(balance_drops),
        "transactions": transactions,
        "transactions_error": tx_error,
        "honesty": {
            "mode": "public_read_only",
            "note": "This pane reads public ledger data only. Connecting a wallet never sends private keys to THREEZONE.",
        },
    }


def _moten_json(method: str, url: str, body: dict | None = None, *, timeout: float = 12.0) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json", "X-Moten-Actor-Role": "IP Steward"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"moten_http_{exc.code}:{detail}") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"moten_unreachable:{type(exc).__name__}") from exc


def to_hex_ascii(value: str) -> str:
    return (value or "").encode("utf-8").hex().upper()


def build_memo_account_set(*, account: str, memo_type: str, memo_data: str) -> dict:
    """Unsigned AccountSet with Moten audit memo for wallet sign+submit."""
    return {
        "TransactionType": "AccountSet",
        "Account": account,
        "Memos": [{
            "Memo": {
                "MemoType": to_hex_ascii(memo_type),
                "MemoData": to_hex_ascii(memo_data),
                "MemoFormat": to_hex_ascii("text/plain"),
            }
        }],
    }


def moten_department_snapshot(moten_base_url: str, *, wallet_address: str | None = None) -> dict:
    base = (moten_base_url or "").rstrip("/")
    if not base:
        return {"configured": False, "error": "moten_onchain_not_configured"}
    health = _moten_json("GET", base + "/api/onchain/health")
    publications = _moten_json("GET", base + "/api/onchain/publications").get("publications") or []
    receipts = _moten_json("GET", base + "/api/onchain/receipts").get("receipts") or []
    profile = _moten_json("GET", base + "/api/onchain/signing-profile").get("signing_profile") or {}
    reconcile = None
    try:
        reconcile = _moten_json("POST", base + "/api/onchain/reconcile", {})
    except RuntimeError as exc:
        reconcile = {"error": str(exc)}

    wallet_txs = []
    if wallet_address:
        try:
            snap = account_snapshot(wallet_address, profile.get("network") or "testnet", tx_limit=50)
            wallet_txs = snap.get("transactions") or []
        except Exception as exc:  # noqa: BLE001
            wallet_txs = []
            health = dict(health)
            health["wallet_read_error"] = type(exc).__name__

    receipt_hashes = {str(r.get("transaction_hash") or "") for r in receipts if r.get("transaction_hash")}
    matched = []
    unmatched_ledger = []
    for tx in wallet_txs:
        h = str(tx.get("hash") or "")
        if h and h in receipt_hashes:
            matched.append({"transaction_hash": h, "ledger_index": tx.get("ledger_index"), "type": tx.get("transaction_type")})
        elif h:
            unmatched_ledger.append(h[:16] + "…")

    unmatched_receipts = [
        {"receipt_id": r.get("receipt_id"), "transaction_hash": r.get("transaction_hash"), "status": r.get("status")}
        for r in receipts
        if r.get("transaction_hash") and str(r.get("transaction_hash")) not in {m["transaction_hash"] for m in matched}
        and r.get("status") != "SIMULATED"
    ]

    return {
        "configured": True,
        "health": health,
        "signing_profile": profile,
        "publications": publications[:50],
        "receipts": receipts[:50],
        "reconciliation": reconcile,
        "match": {
            "matched": matched,
            "unmatched_receipt_count": len(unmatched_receipts),
            "unmatched_receipts": unmatched_receipts[:20],
            "wallet_tx_count": len(wallet_txs),
        },
        "honesty": {
            "treasure": (health.get("honesty") or {}).get("treasure") or "simulated_verification_only",
            "publish": (health.get("honesty") or {}).get("publish") or "wallet_signed_memo_or_simulation",
            "mode_note": (health.get("honesty") or {}).get("mode_note") or "",
            "xrpl_mode": health.get("xrpl_mode"),
            "network": health.get("network"),
            "xrpl_label": health.get("xrpl"),
            "wallet_signed_publication_supported": health.get("wallet_signed_publication_supported", True),
        },
    }


def bind_moten_audit_account(moten_base_url: str, *, account: str, network: str = "testnet") -> dict:
    base = (moten_base_url or "").rstrip("/")
    if not base:
        raise RuntimeError("moten_onchain_not_configured")
    account = validate_classic_address(account)
    network = normalize_network(network)
    return _moten_json(
        "POST",
        base + "/api/onchain/signing-profile/account",
        {"account": account, "network": network},
    )


def prepare_wallet_test_publish(moten_base_url: str, *, account: str, network: str = "testnet") -> dict:
    """Create Moten evidence.manifest → verify → publication request + unsigned AccountSet."""
    base = (moten_base_url or "").rstrip("/")
    if not base:
        raise RuntimeError("moten_onchain_not_configured")
    account = validate_classic_address(account)
    network = normalize_network(network)
    bind_moten_audit_account(base, account=account, network=network)

    import time
    import uuid

    event_id = f"EVT-OPS-{uuid.uuid4().hex[:12].upper()}"
    event_body = {
        "event_id": event_id,
        "event_type": "evidence.manifest.created",
        "organization_id": "THREE_ZONE_KC",
        "source_system": "three-zone-ops",
        "object_id": f"OPS-MANIFEST-{uuid.uuid4().hex[:8].upper()}",
        "object_version": "v1",
        "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "actor_type": "human",
        "actor_id": "ops-operator",
        "actor_role": "IP Steward",
        "action": "create_evidence_manifest",
        "payload": {
            "purpose": "ops_wallet_test_publish",
            "network": network,
            "audit_account": account,
        },
        "classification": "CONFIDENTIAL_HASH_ONLY",
    }
    created = _moten_json("POST", base + "/api/audit/events", event_body)
    event = created.get("event") or {}
    verification = _moten_json("POST", base + f"/api/treasure/verifications/{event_id}", {}).get("verification") or {}
    if verification.get("verification_status") != "VERIFIED":
        raise RuntimeError("moten_verification_failed")
    publication = _moten_json(
        "POST",
        base + "/api/onchain/publications",
        {"event_id": event_id, "verification_id": verification.get("verification_id")},
    ).get("publication") or {}

    memo_data = event.get("canonical_event_hash") or ""
    unsigned_tx = build_memo_account_set(
        account=account,
        memo_type="moten.audit.v1",
        memo_data=memo_data,
    )
    return {
        "event_id": event_id,
        "canonical_event_hash": memo_data,
        "verification_id": verification.get("verification_id"),
        "verification_status": verification.get("verification_status"),
        "request_id": publication.get("request_id"),
        "publication_status": publication.get("status"),
        "network": network,
        "account": account,
        "unsigned_tx": unsigned_tx,
        "instructions": "Sign and submit unsigned_tx with Crossmark/GemWallet, then confirm with the transaction hash.",
        "honesty": {
            "means": "wallet_signed_accountset_memo",
            "not": "treasure_path_a_release",
        },
    }


def confirm_wallet_test_publish(
    moten_base_url: str,
    *,
    request_id: str,
    transaction_hash: str,
    account: str,
    network: str = "testnet",
) -> dict:
    base = (moten_base_url or "").rstrip("/")
    if not base:
        raise RuntimeError("moten_onchain_not_configured")
    return _moten_json(
        "POST",
        base + "/api/onchain/publications/wallet-confirm",
        {
            "request_id": request_id,
            "transaction_hash": transaction_hash,
            "account": account,
            "network": network,
        },
    )
