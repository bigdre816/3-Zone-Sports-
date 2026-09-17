"""Short-lived, single-use WebSocket tickets.

Minted from an already-authenticated HTTP session. The raw token is never
stored; only SHA-256 is kept. Handshake carries ``ticket.<token>`` in
``Sec-WebSocket-Protocol`` so the long-lived session never touches the socket.
"""

from __future__ import annotations

import hashlib
import secrets
import time

from .control_plane import ForbiddenError, NotFoundError, ValidationError

TICKET_TTL_SECONDS = 45
TICKET_PREFIX = "ticket."


class TicketError(Exception):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _hash_ticket(raw: str) -> str:
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def _new_token() -> str:
    # urlsafe, no padding, legal Sec-WebSocket-Protocol token characters.
    return secrets.token_urlsafe(32).rstrip("=")


def mint_ticket(cp, user: dict, body: dict | None, ws_url_for) -> dict:
    """Create a single-use ticket bound to a member and an event or party."""
    body = body or {}
    event_id = (body.get("event_id") or "").strip()
    party_id = (body.get("party_id") or "").strip()
    if bool(event_id) == bool(party_id):
        raise ValidationError("provide event_id or party_id", "bad_ticket_target")
    if party_id:
        if not party_id.startswith("party_"):
            raise ValidationError("invalid party id", "bad_ticket_target")
        party = cp.db.query_one("SELECT * FROM watch_parties WHERE party_id=?", (party_id,))
        if not party:
            raise NotFoundError("unknown party", "unknown_party")
        profile = cp.db.query_one("SELECT * FROM profiles WHERE user_id=?", (user["user_id"],))
        member = None
        if profile:
            member = cp.db.query_one(
                "SELECT 1 FROM watch_party_members WHERE party_id=? AND profile_id=? AND left_at IS NULL",
                (party_id, profile["profile_id"]),
            )
        if not member:
            raise ForbiddenError("not in this party", "not_in_party")
        target_type, target_id = "party", party_id
        ws_url = ws_url_for("party", party_id)
    else:
        if not event_id.startswith("evt_"):
            raise ValidationError("invalid event id", "bad_ticket_target")
        try:
            event_row = cp.get_event_row(event_id)
        except Exception as exc:
            raise NotFoundError("unknown event", "unknown_event") from exc
        if "*" not in user["zones"] and event_row["zone"] not in user["zones"]:
            raise ForbiddenError("zone not entitled", "zone_not_entitled")
        target_type, target_id = "event", event_id
        ws_url = ws_url_for("event", event_id)

    raw = _new_token()
    now = time.time()
    expires_at = now + TICKET_TTL_SECONDS
    cp.db.execute(
        "INSERT INTO ws_tickets(ticket_hash, user_id, target_type, target_id, expires_at, consumed_at, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (_hash_ticket(raw), user["user_id"], target_type, target_id, expires_at, None, now),
    )
    cp.audit_log(
        user["user_id"], "ws.ticket.minted", target_id,
        {"target_type": target_type, "expires_in": TICKET_TTL_SECONDS, "legal_effect": "provenance_only"},
    )
    return {
        "ticket": raw,
        "expires_in": TICKET_TTL_SECONDS,
        "ws_url": ws_url,
        "target_type": target_type,
        "target_id": target_id,
    }


def consume_ticket(cp, raw: str, target_id: str) -> dict:
    """Burn a ticket. Fail closed on unknown, expired, replay, or target mismatch."""
    if not raw or any(ch in raw for ch in " \r\n"):
        raise TicketError("invalid ticket", "invalid")
    digest = _hash_ticket(raw)
    now = time.time()

    def _txn(conn):
        sql = cp.db._prepare_sql
        row = conn.execute(sql("SELECT * FROM ws_tickets WHERE ticket_hash=?"), (digest,)).fetchone()
        if not row:
            raise TicketError("unknown ticket", "unknown")
        row = dict(row)
        if row.get("consumed_at") is not None:
            raise TicketError("ticket already used", "replay")
        if float(row["expires_at"]) <= now:
            raise TicketError("ticket expired", "expired")
        if row["target_id"] != target_id:
            raise TicketError("ticket target mismatch", "target_mismatch")
        cur = conn.execute(
            sql("UPDATE ws_tickets SET consumed_at=? WHERE ticket_hash=? AND consumed_at IS NULL"),
            (now, digest),
        )
        if getattr(cur, "rowcount", 1) == 0:
            raise TicketError("ticket already used", "replay")
        return row

    row = cp.db.write_transaction(_txn)
    user = cp.get_user(row["user_id"])
    if not user:
        raise TicketError("invalid session", "invalid_session")
    cp.audit_log(
        user["user_id"], "ws.ticket.consumed", target_id,
        {"target_type": row["target_type"], "legal_effect": "provenance_only"},
    )
    return user
