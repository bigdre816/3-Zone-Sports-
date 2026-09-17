"""Short-lived, single-use tickets for the WebSocket handshake.

The long-lived member credential (the ``tz_member_session`` cookie or a bearer
session token) must never travel in ``Sec-WebSocket-Protocol``: that header is
easy to leak through proxies, logs and browser tooling, and it cannot be
marked HttpOnly. Instead an already-authenticated HTTP request asks for a
ticket, and only the ticket is offered during the handshake.

Properties:
  * random 128-bit value, base64url encoded, so it is a legal subprotocol token
  * short lived (default 45 seconds)
  * single use -- redeeming burns the row
  * bound to the member and, optionally, to one event id
  * the credential it stands for is stored server-side and never leaves the DB
"""

from __future__ import annotations

import base64
import os
import time

TICKET_PREFIX = "ticket."
TICKET_TTL_SECONDS = 45


def _now() -> float:
    return time.time()


def mint(db, *, user_id: str, credential_kind: str, credential: str,
         event_id: str = "", ttl: int = TICKET_TTL_SECONDS) -> tuple[str, int]:
    """Create a ticket for ``credential``. Returns (ticket_value, ttl)."""
    raw = base64.urlsafe_b64encode(os.urandom(16)).decode("ascii").rstrip("=")
    ticket = TICKET_PREFIX + raw
    db.execute(
        "INSERT INTO ws_tickets (ticket, user_id, event_id, credential_kind,"
        " credential, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ticket, user_id, event_id or "", credential_kind, credential,
         _now(), _now() + ttl),
    )
    prune(db)
    return ticket, ttl


def prune(db) -> None:
    """Drop expired tickets. Cheap; the table stays tiny."""
    try:
        db.execute("DELETE FROM ws_tickets WHERE expires_at < ?", (_now() - 300,))
    except Exception:
        pass


def redeem(db, ticket: str, event_id: str = "") -> tuple[str, str] | None:
    """Burn ``ticket`` and return (credential_kind, credential), or None.

    None covers every failure the caller must treat identically: unknown,
    already used, expired, or bound to a different event. A ticket bound to an
    event is rejected on every other path, including paths that carry no event
    id at all -- binding narrows authority and can never widen it.
    """
    if not ticket or not ticket.startswith(TICKET_PREFIX):
        return None
    row = db.query_one(
        "SELECT user_id, event_id, credential_kind, credential, expires_at"
        " FROM ws_tickets WHERE ticket = ?",
        (ticket,),
    )
    # single use: burn on sight, valid or not
    db.execute("DELETE FROM ws_tickets WHERE ticket = ?", (ticket,))
    if not row:
        return None
    bound_event = row["event_id"] if not isinstance(row, tuple) else row[1]
    expires_at = row["expires_at"] if not isinstance(row, tuple) else row[4]
    kind = row["credential_kind"] if not isinstance(row, tuple) else row[2]
    credential = row["credential"] if not isinstance(row, tuple) else row[3]
    if float(expires_at or 0) < _now():
        return None
    # Authority must never widen: a ticket bound to one event is valid only
    # on that event's path. An empty ``event_id`` (watch-party or any other
    # non-event path) is a *different* target, not a wildcard.
    if bound_event and bound_event != event_id:
        return None
    return str(kind), str(credential)
