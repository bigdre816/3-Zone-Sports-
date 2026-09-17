"""Same-port public gateway: in-process Hub for ``/ws/*``, HTTP splice otherwise.

Render exposes one ``$PORT``. The Hub stays in this process (subscribers and
outbox share memory). Non-upgrade traffic is TCP-spliced to the existing
``ThreadingHTTPServer`` on loopback so uploads and Range media keep streaming.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from websockets.asyncio.server import ServerConnection
from websockets.frames import CloseCode
from websockets.protocol import OPEN
from websockets.server import ServerProtocol

from .config import Config
from .ws_server import PATH_PREFIX, PARTY_PREFIX, SUBPROTOCOL, Hub

_LOG = logging.getLogger("threezone.gateway")
_MAX_HEADER = 64 * 1024
_WS_PATHS = (PATH_PREFIX, PARTY_PREFIX)


def _is_ws_upgrade(header_bytes: bytes) -> bool:
    try:
        head, _sep, _rest = header_bytes.partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        if not lines:
            return False
        request_line = lines[0].decode("latin1", "replace")
        parts = request_line.split(" ")
        if len(parts) < 2 or parts[0].upper() != "GET":
            return False
        path = parts[1].split("?", 1)[0]
        if not any(path.startswith(prefix) for prefix in _WS_PATHS):
            return False
        headers = {}
        for raw in lines[1:]:
            if b":" not in raw:
                continue
            name, value = raw.split(b":", 1)
            headers[name.strip().lower()] = value.strip().lower()
        connection = headers.get(b"connection", b"")
        upgrade = headers.get(b"upgrade", b"")
        return b"upgrade" in connection and upgrade == b"websocket"
    except Exception:
        return False


class _Pipe(asyncio.Protocol):
    """One direction of a TCP splice."""

    def __init__(self) -> None:
        self.peer: asyncio.Transport | None = None
        self._buffer = bytearray()

    def set_peer(self, peer: asyncio.Transport) -> None:
        self.peer = peer
        if self._buffer and not peer.is_closing():
            peer.write(bytes(self._buffer))
            self._buffer.clear()

    def data_received(self, data: bytes) -> None:
        if self.peer is None or self.peer.is_closing():
            self._buffer.extend(data)
            return
        self.peer.write(data)

    def connection_lost(self, exc: Exception | None) -> None:
        if self.peer is not None and not self.peer.is_closing():
            self.peer.close()


class _WsBridge:
    """Minimal server adapter so ``ServerConnection`` can run Hub in-process."""

    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.handler_tasks: set[asyncio.Task] = set()
        self.all_connections: set[ServerConnection] = set()
        self._serving = True

    def is_serving(self) -> bool:
        return self._serving

    def stop(self) -> None:
        self._serving = False

    async def handler(self, connection: ServerConnection) -> None:
        try:
            await connection.handshake(server_header=None)
            if connection.protocol.state is not OPEN:
                connection.transport.abort()
                return
            self.all_connections.add(connection)
            connection.start_keepalive()
            try:
                await self.hub.handle(connection)
            except Exception:
                _LOG.exception("hub handler failed")
                await connection.close(CloseCode.INTERNAL_ERROR)
            else:
                await connection.close()
            finally:
                self.all_connections.discard(connection)
        except Exception:
            try:
                connection.transport.abort()
            except Exception:
                pass


class GatewayProtocol(asyncio.Protocol):
    def __init__(self, gateway: "Gateway") -> None:
        self.gateway = gateway
        self.transport: asyncio.Transport | None = None
        self.buffer = bytearray()
        self.mode = "headers"

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def data_received(self, data: bytes) -> None:
        if self.mode != "headers":
            return
        self.buffer.extend(data)
        if len(self.buffer) > _MAX_HEADER:
            self.transport.close()
            return
        if b"\r\n\r\n" not in self.buffer:
            return
        header_bytes = bytes(self.buffer)
        self.buffer.clear()
        if _is_ws_upgrade(header_bytes):
            self.mode = "ws"
            self.gateway.takeover_websocket(self.transport, header_bytes)
            return
        self.mode = "http"
        self.transport.pause_reading()
        asyncio.create_task(self.gateway.splice_http(self.transport, header_bytes))

    def connection_lost(self, exc: Exception | None) -> None:
        return


class Gateway:
    def __init__(self, config: Config, hub: Hub, http_port: int, http_host: str = "127.0.0.1"):
        self.config = config
        self.hub = hub
        self.http_port = http_port
        self.http_host = http_host
        self.bridge = _WsBridge(hub)
        self._stop = asyncio.Event()

    def takeover_websocket(self, transport: asyncio.Transport, header_bytes: bytes) -> None:
        protocol = ServerProtocol(
            origins=None,
            subprotocols=[SUBPROTOCOL],
            max_size=self.config.ws_max_message_bytes,
        )
        connection = ServerConnection(
            protocol,
            self.bridge,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=10,
        )
        transport.set_protocol(connection)
        connection.connection_made(transport)
        connection.data_received(header_bytes)

    async def splice_http(self, client: asyncio.Transport, header_bytes: bytes) -> None:
        loop = asyncio.get_running_loop()
        backend_proto = _Pipe()
        try:
            b_transport, _ = await loop.create_connection(
                lambda: backend_proto, self.http_host, self.http_port
            )
        except Exception:
            if not client.is_closing():
                client.close()
            return
        client_proto = _Pipe()
        client.set_protocol(client_proto)
        client_proto.set_peer(b_transport)
        backend_proto.set_peer(client)
        try:
            b_transport.write(header_bytes)
        except Exception:
            client.close()
            b_transport.close()
            return
        if not client.is_closing():
            client.resume_reading()

    def request_stop(self) -> None:
        self.bridge.stop()
        self.hub.request_stop()
        self._stop.set()

    async def serve(self) -> None:
        loop = asyncio.get_running_loop()
        tasks = [
            asyncio.create_task(self.hub.outbox_loop()),
            asyncio.create_task(self.hub.feed_loop()),
            asyncio.create_task(self.hub.metrics_loop()),
        ]

        def _graceful(*_):
            self.request_stop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _graceful)
            except (NotImplementedError, ValueError, RuntimeError):
                pass

        server = await loop.create_server(
            lambda: GatewayProtocol(self),
            self.config.http_host,
            self.config.http_port,
        )
        async with server:
            await self._stop.wait()
            server.close()
            await server.wait_closed()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def run_gateway(config: Config, hub: Hub, http_port: int, http_host: str = "127.0.0.1") -> None:
    gateway = Gateway(config, hub, http_port, http_host)
    await gateway.serve()


def start_http_thread(httpd, daemon: bool = True):
    import threading
    thread = threading.Thread(target=httpd.serve_forever, daemon=daemon)
    thread.start()
    return thread
