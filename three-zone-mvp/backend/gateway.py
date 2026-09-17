"""Same-public-port gateway.

Render exposes exactly one public port per web service. Before this module the
member portal could never open a live socket: ``run.py`` starts the WebSocket
process with ``bind_socket=False`` on Render, so nothing was listening on
``TZ_WS_PORT`` at all, and ``public_config()`` advertised ``0.0.0.0:8765``,
which is a bind address rather than a browser destination.

This gateway owns the public port. For each new connection it reads only the
request head, decides where the connection belongs, and then splices the raw
TCP stream to one of two loopback listeners:

    Render public $PORT  ->  this gateway
                               |-- Upgrade: websocket on /ws/*  -> ws_server Hub
                               `-- everything else              -> http_server

Deliberately *not* implemented here: WebSocket framing, ping/pong, close-code
translation, per-message limits, backpressure policy. Those all continue to
live in the already-hardened Hub in ``ws_server.py`` and stay end-to-end
between the browser and that Hub -- this layer only moves bytes. The same is
true for HTTP: keep-alive, chunked bodies and streaming responses pass through
untouched because nothing here parses past the first header block.

Fan-out remains single-instance scoped. Running more than one Render instance
requires shared pub/sub (Redis or a managed realtime layer) before viewers on
different instances can see the same live event; see docs/LIVE-SOCKETS.md.
"""

from __future__ import annotations

import asyncio
import os

_HEAD_LIMIT = 64 * 1024
_HEAD_TIMEOUT = 15.0
_WS_PATH_PREFIXES = ("/ws/",)


def gateway_enabled() -> bool:
    """Whether to front the stdlib HTTP server with this gateway.

    Defaults on when Render injects ``RENDER=true``; ``TZ_GATEWAY=0`` opts out
    and ``TZ_GATEWAY=1`` opts in locally.
    """
    raw = os.environ.get("TZ_GATEWAY", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return os.environ.get("RENDER", "").strip().lower() in ("1", "true", "yes")


def _parse_head(head: bytes) -> tuple[str, dict[str, str]]:
    """Return (path, lowercased headers) from a raw request head."""
    lines = head.split(b"\r\n")
    request_line = lines[0].decode("latin-1", "replace") if lines else ""
    parts = request_line.split(" ")
    path = parts[1] if len(parts) >= 2 else "/"
    headers: dict[str, str] = {}
    for raw_line in lines[1:]:
        if not raw_line or b":" not in raw_line:
            continue
        name, _, value = raw_line.decode("latin-1", "replace").partition(":")
        headers[name.strip().lower()] = value.strip()
    return path, headers


def _is_websocket(path: str, headers: dict[str, str]) -> bool:
    upgrade = headers.get("upgrade", "").lower()
    connection = headers.get("connection", "").lower()
    if "websocket" not in upgrade or "upgrade" not in connection:
        return False
    return any(path.startswith(prefix) for prefix in _WS_PATH_PREFIXES)


def _with_forwarded(head: bytes, peer_ip: str, scheme: str) -> bytes:
    """Append forwarding headers so the backend sees the real client."""
    if not peer_ip:
        return head
    lines = head.split(b"\r\n")
    existing = {
        line.split(b":", 1)[0].strip().lower()
        for line in lines[1:]
        if b":" in line
    }
    extra: list[bytes] = []
    if b"x-forwarded-for" not in existing:
        extra.append(b"X-Forwarded-For: " + peer_ip.encode("latin-1", "replace"))
    if b"x-forwarded-proto" not in existing:
        extra.append(b"X-Forwarded-Proto: " + scheme.encode("latin-1"))
    if not extra:
        return head
    # head ends with the blank line terminator; insert just before it.
    body_sep = b"\r\n\r\n"
    if head.endswith(body_sep):
        return head[: -len(body_sep)] + b"\r\n" + b"\r\n".join(extra) + body_sep
    return head


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            writer.write_eof()
        except Exception:
            pass


class Gateway:
    def __init__(self, public_host: str, public_port: int,
                 http_target: tuple[str, int], ws_target: tuple[str, int],
                 forwarded_proto: str = "https") -> None:
        self.public_host = public_host
        self.public_port = public_port
        self.http_target = http_target
        self.ws_target = ws_target
        self.forwarded_proto = forwarded_proto

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        upstream_writer: asyncio.StreamWriter | None = None
        try:
            try:
                head = await asyncio.wait_for(
                    reader.readuntil(b"\r\n\r\n"), timeout=_HEAD_TIMEOUT
                )
            except asyncio.LimitOverrunError:
                writer.write(b"HTTP/1.1 431 Request Header Fields Too Large\r\n"
                             b"Connection: close\r\n\r\n")
                await writer.drain()
                return
            except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                return

            if len(head) > _HEAD_LIMIT:
                writer.write(b"HTTP/1.1 431 Request Header Fields Too Large\r\n"
                             b"Connection: close\r\n\r\n")
                await writer.drain()
                return

            path, headers = _parse_head(head)
            target = self.ws_target if _is_websocket(path, headers) else self.http_target

            peer = writer.get_extra_info("peername")
            peer_ip = peer[0] if isinstance(peer, tuple) and peer else ""
            head = _with_forwarded(head, peer_ip, self.forwarded_proto)

            try:
                upstream_reader, upstream_writer = await asyncio.wait_for(
                    asyncio.open_connection(*target), timeout=10.0
                )
            except (OSError, asyncio.TimeoutError):
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\n"
                             b"Content-Length: 0\r\nConnection: close\r\n\r\n")
                await writer.drain()
                return

            upstream_writer.write(head)
            await upstream_writer.drain()

            await asyncio.gather(
                _pipe(reader, upstream_writer),
                _pipe(upstream_reader, writer),
                return_exceptions=True,
            )
        except Exception:
            pass
        finally:
            for w in (upstream_writer, writer):
                if w is None:
                    continue
                try:
                    w.close()
                except Exception:
                    pass

    async def serve_forever(self) -> None:
        server = await asyncio.start_server(
            self._handle, self.public_host, self.public_port, limit=_HEAD_LIMIT
        )
        async with server:
            await server.serve_forever()


def run_gateway(public_host: str, public_port: int,
                http_target: tuple[str, int], ws_target: tuple[str, int],
                forwarded_proto: str = "https") -> None:
    """Blocking entry point for the gateway process."""
    gateway = Gateway(public_host, public_port, http_target, ws_target, forwarded_proto)
    try:
        asyncio.run(gateway.serve_forever())
    except KeyboardInterrupt:  # pragma: no cover
        pass
