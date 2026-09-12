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
