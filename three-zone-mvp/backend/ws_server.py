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

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from . import tokens
from .config import Config
from .control_plane import ControlPlane
from .db import Database, dumps, loads

SUBPROTOCOL = "tz-session"
_PATH_PREFIX = "/ws/events/"


class Hub:
    def __init__(self, cp: ControlPlane):
        self.cp = cp
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
        if not path.startswith(_PATH_PREFIX):
            await ws.close(1008, "unknown path")
            return
        event_id = path[len(_PATH_PREFIX):].strip("/")

        token = self._offered_token(request)
        if not token:
            await ws.close(1008, "missing session token")
            return
        try:
            user = self.cp.verify_session(token)
        except Exception:
            await ws.close(1008, "invalid session")
            return

        try:
            event_row = self.cp.get_event_row(event_id)
        except Exception:
            await ws.close(1008, "unknown event")
            return
        if "*" not in user["zones"] and event_row["zone"] not in user["zones"]:
            await ws.close(1008, "zone not entitled")
            return

        if self.ip_counts[peer] >= self.cp.config.ws_max_conns_per_ip:
            await ws.close(1013, "per-IP connection limit reached")
            return

        self.ip_counts[peer] += 1
        self.subscribers[event_id].add(ws)
        ws_user_id = user["user_id"]
        try:
            await self._send(ws, {"type": "event.state", "event_id": event_id,
                                  "snapshot": self.cp._event_dict(event_row)})
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
            # A lease-renewal attempt: re-run authorization against live state.
            user = self.cp.get_user(user_id)
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
                    await self.broadcast(row["event_id"],
                                         {"type": row["type"], "event_id": row["event_id"], **payload})
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
    hub = Hub(cp)

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
