"""Separate WebSocket process: event-state, feed-heartbeat, lease-renewal, and
rights-revocation broadcasts.

Hardening implemented here:
- browser ``Origin`` allowlist checked before a socket is admitted,
- session token carried in ``Sec-WebSocket-Protocol`` (never in the URL),
- max message size, per-connection message rate limit, per-IP connection limit,
- library ping/pong keepalive with timeout, and clean shutdown.

Cross-process fan-out uses a transactional outbox in SQLite: the HTTP process
writes ``socket_outbox`` rows; this process polls, delivers to subscribers, and
marks them delivered. Connection counts are published to ``socket_metrics`` so
``/api/analytics`` can report them.
"""

from __future__ import annotations

import asyncio
import collections
import json
import signal
import time
from http.cookies import SimpleCookie

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from .config import Config
from .control_plane import ControlPlane
from .db import Database, dumps, loads
from .portal import PortalService

SUBPROTOCOL = "tz-session"
_PATH_PREFIX = "/ws/events/"
_PARTY_PREFIX = "/ws/watch-parties/"


class Hub:
    def __init__(self, cp: ControlPlane, portal: PortalService | None = None):
        self.cp = cp
        self.portal = portal or PortalService(cp)
        self.subscribers: dict[str, set] = collections.defaultdict(set)
        self.ip_counts: collections.Counter = collections.Counter()
        self._feed_state: dict[str, tuple] = {}
        self._stop = asyncio.Event()

    # -- helpers ----------------------------------------------------------
    def _offered_token(self, request) -> str | None:
        values = request.headers.get_all("Sec-WebSocket-Protocol")
        offered: list[str] = []
        for value in values:
            offered.extend(part.strip() for part in value.split(",") if part.strip())
        for item in offered:
            if item != SUBPROTOCOL:
                return item
        return None

    def _cookie_session(self, request) -> str | None:
        raw = request.headers.get("Cookie") or ""
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:
            return None
        morsel = jar.get("tz_member_session")
        return morsel.value if morsel else None

    def _user_from_request(self, request):
        token = self._offered_token(request)
        if token:
            return self.cp.verify_session(token)
        sid = self._cookie_session(request)
        if sid:
            _row, user = self.portal.session(sid)
            return user
        raise LookupError("missing session token")

    async def _send(self, ws, obj: dict) -> None:
        try:
            await ws.send(json.dumps(obj))
        except ConnectionClosed:
            pass

    async def broadcast(self, event_id: str, obj: dict) -> None:
        for ws in list(self.subscribers.get(event_id, ())):
            await self._send(ws, obj)

    # -- connection handler ----------------------------------------------
    async def handle(self, ws) -> None:
        request = ws.request
        path = request.path
        origin = request.headers.get("Origin")
        peer = ws.remote_address[0] if ws.remote_address else "unknown"

        if origin is not None and origin not in self.cp.config.allowed_origins:
            await ws.close(1008, "origin not allowed")
            return
        try:
            user = self._user_from_request(request)
        except Exception:
            await ws.close(1008, "invalid session")
            return

        event_row = None
        if path.startswith(_PARTY_PREFIX):
            party_id = path[len(_PARTY_PREFIX):].strip("/")
            if not party_id.startswith("party_"):
                await ws.close(1008, "unknown path")
                return
            party = self.cp.db.query_one("SELECT * FROM watch_parties WHERE party_id=?", (party_id,))
            if not party:
                await ws.close(1008, "unknown party")
                return
            profile = self.cp.db.query_one("SELECT * FROM profiles WHERE user_id=?", (user["user_id"],))
            member = None
            if profile:
                member = self.cp.db.query_one(
                    "SELECT 1 FROM watch_party_members WHERE party_id=? AND profile_id=? AND left_at IS NULL",
                    (party_id, profile["profile_id"]),
                )
            if not member:
                await ws.close(1008, "not in this party")
                return
            event_id = party_id
            snapshot = {"party_id": party_id, "event_id": party["event_id"], "status": party["status"]}
        elif path.startswith(_PATH_PREFIX):
            event_id = path[len(_PATH_PREFIX):].strip("/")
            try:
                event_row = self.cp.get_event_row(event_id)
            except Exception:
                await ws.close(1008, "unknown event")
                return
            if "*" not in user["zones"] and event_row["zone"] not in user["zones"]:
                await ws.close(1008, "zone not entitled")
                return
            snapshot = self.cp._event_dict(event_row)
        else:
            await ws.close(1008, "unknown path")
            return

        if self.ip_counts[peer] >= self.cp.config.ws_max_conns_per_ip:
            await ws.close(1013, "per-IP connection limit reached")
            return

        self.ip_counts[peer] += 1
        self.subscribers[event_id].add(ws)
        ws_user_id = user["user_id"]
        try:
            await self._send(ws, {"type": "event.state", "event_id": event_id, "snapshot": snapshot})
            await self._recv_loop(ws, event_id, ws_user_id)
        finally:
            self.subscribers[event_id].discard(ws)
            self.ip_counts[peer] -= 1
            if self.ip_counts[peer] <= 0:
                del self.ip_counts[peer]

    async def _recv_loop(self, ws, event_id: str, user_id: str) -> None:
        window = collections.deque()
        limit = self.cp.config.ws_max_messages_per_10s
        try:
            async for raw in ws:
                nowts = time.monotonic()
                window.append(nowts)
                while window and nowts - window[0] > 10:
                    window.popleft()
                if len(window) > limit:
                    await ws.close(1008, "message rate limit exceeded")
                    return
                await self._on_message(ws, event_id, user_id, raw)
        except ConnectionClosed:
            return

    async def _on_message(self, ws, event_id: str, user_id: str, raw) -> None:
        try:
            msg = json.loads(raw)
            kind = msg.get("type")
        except (ValueError, AttributeError):
            return
        if kind == "ping":
            await self._send(ws, {"type": "pong", "ts": time.time()})
        elif kind == "renew":
            user = self.cp.get_user(user_id)
            if event_id.startswith("party_"):
                await self._send(ws, {"type": "lease.status", "allow": True, "reason": "social_only"})
                return
            try:
                row = self.cp.get_event_row(event_id)
            except Exception:
                await self._send(ws, {"type": "lease.status", "allow": False, "reason": "event_not_found"})
                return
            decision = self.cp.evaluate_access(user, row) if user else {"allow": False, "code": "invalid_session"}
            await self._send(ws, {"type": "lease.status", "allow": decision["allow"],
                                  "reason": decision.get("code")})

    # -- background loops -------------------------------------------------
    async def outbox_loop(self) -> None:
        while not self._stop.is_set():
            try:
                rows = self.cp.db.query(
                    "SELECT * FROM socket_outbox WHERE delivered=0 ORDER BY id ASC LIMIT 200"
                )
                for row in rows:
                    payload = loads(row["payload"], {})
                    message = {"type": row["type"], "event_id": row["event_id"], **payload}
                    await self.broadcast(row["event_id"], message)
                    if row["type"] in ("rights.revoked", "score.update", "moment.published", "event.state"):
                        parties = self.cp.db.query(
                            "SELECT party_id FROM watch_parties WHERE event_id=? AND status='open'",
                            (row["event_id"],),
                        )
                        for party in parties:
                            await self.broadcast(party["party_id"], message)
                    self.cp.db.execute("UPDATE socket_outbox SET delivered=1 WHERE id=?", (row["id"],))
            except Exception:
                pass
            await asyncio.sleep(0.3)

    async def feed_loop(self) -> None:
        """Detect primary timeouts, fail over to backup, and return to primary
        on a fresh primary heartbeat, broadcasting changes."""
        while not self._stop.is_set():
            try:
                rows = self.cp.db.query(
                    "SELECT * FROM events WHERE status IN ('green','live')"
                )
                for row in rows:
                    effective = self.cp._effective_source(row)
                    healthy = self.cp._feed_healthy(row, effective)
                    if effective != row["active_source"]:
                        self.cp.db.execute("UPDATE events SET active_source=? WHERE event_id=?",
                                           (effective, row["event_id"]))
                        self.cp.audit_log("system", "feed.failover", row["event_id"],
                                          {"from": row["active_source"], "to": effective})
                    state = (effective, healthy)
                    if self._feed_state.get(row["event_id"]) != state:
                        self._feed_state[row["event_id"]] = state
                        await self.broadcast(row["event_id"], {
                            "type": "feed.heartbeat", "event_id": row["event_id"],
                            "active_source": effective, "feed_healthy": healthy,
                        })
            except Exception:
                pass
            await asyncio.sleep(2.0)

    async def metrics_loop(self) -> None:
        while not self._stop.is_set():
            try:
                per_event = {eid: len(conns) for eid, conns in self.subscribers.items() if conns}
                total = sum(per_event.values())
                self.cp.db.execute(
                    "UPDATE socket_metrics SET connections=?, per_event=?, updated_at=? WHERE id=1",
                    (total, dumps(per_event), time.time()),
                )
            except Exception:
                pass
            await asyncio.sleep(3.0)

    def request_stop(self) -> None:
        self._stop.set()


async def ws_main(config: Config) -> None:
    db = Database(config.database_locator)
    cp = ControlPlane(db, config)
    hub = Hub(cp, PortalService(cp))

    loop = asyncio.get_running_loop()
    stop = asyncio.Future()

    def _graceful(*_):
        if not stop.done():
            stop.set_result(None)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _graceful)
        except (NotImplementedError, ValueError):  # pragma: no cover
            pass

    tasks = [asyncio.create_task(hub.outbox_loop()),
             asyncio.create_task(hub.feed_loop()),
             asyncio.create_task(hub.metrics_loop())]

    async with serve(
        hub.handle, config.ws_host, config.ws_port,
        subprotocols=[SUBPROTOCOL],
        max_size=config.ws_max_message_bytes,
        ping_interval=20, ping_timeout=20,
    ):
        await stop

    hub.request_stop()
    for task in tasks:
        task.cancel()
    db.close()


def run_ws_process(config: Config) -> None:
    """Entry point for the separate WebSocket process."""
    try:
        asyncio.run(ws_main(config))
    except KeyboardInterrupt:  # pragma: no cover
        pass
