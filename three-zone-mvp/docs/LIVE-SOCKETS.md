# Live sockets on Render (same public port)

## The problem this solves

Render publicly routes **one** port per web service. HTTP and WebSocket traffic
must both arrive on that port, and public socket URLs must use `wss://`.

Before this change:

* `run.py` started the WebSocket process with `bind_socket=False` whenever
  `running_on_render()` was true (`bind_separate_websocket()` in
  `backend/config.py`). The process kept running the outbox, feed and metrics
  loops, but **nothing listened on `TZ_WS_PORT`** — there was no private
  `localhost:8765` socket on Render to forward to.
* `public_config()` advertised `ws://0.0.0.0:8765/ws/events/`. `0.0.0.0` is a
  bind address, not a destination, so `ws_enabled` was false and every client
  fell back to polling.

## The shape now

```text
Render public $PORT
  └── backend/gateway.py            asyncio, owns the public port
        ├── Upgrade: websocket on /ws/*  ──► ws_server.py Hub  (127.0.0.1:8765)
        └── everything else              ──► http_server.py    (127.0.0.1:$PORT+1)
```

The gateway reads only the request head, picks a target, and then splices the
raw TCP stream. It implements **no** WebSocket framing, ping/pong, close-code
translation, message limits or backpressure policy — all of that stays in the
already-hardened `Hub` and runs end to end between the browser and the Hub.
HTTP keep-alive, chunked bodies and streaming responses pass through untouched
for the same reason. The control plane was not rewritten.

Enabled automatically when Render sets `RENDER=true`; `TZ_GATEWAY=1` / `0`
forces it on or off locally.

| Variable | Meaning |
| --- | --- |
| `TZ_GATEWAY` | `1`/`0` override for the gateway (default: on under Render) |
| `TZ_INTERNAL_HTTP_PORT` | loopback port for the stdlib HTTP app (default `$PORT + 1`) |
| `TZ_WS_PUBLIC_ORIGIN` | public origin advertised to clients; falls back to `RENDER_EXTERNAL_URL`, then `TZ_PUBLIC_BASE_URL` |

`public_ws_url_base()` now returns `wss://<public-origin>/ws/events/` in gateway
mode, and an empty string (so `ws_enabled` is false) when there is genuinely no
browser-reachable socket. It never advertises `0.0.0.0` again.

**Origin allowlist:** the browser's `Origin` on the socket handshake is the
portal's domain. Any portal origin that should hold live sockets must be in
`TZ_ALLOWED_ORIGINS`, or the Hub closes with `1008 origin not allowed`.

## Handshake authentication: short-lived tickets

The long-lived member credential (the `tz_member_session` cookie or a bearer
session token) must never travel in `Sec-WebSocket-Protocol` — that header
cannot be HttpOnly and leaks easily through proxies and logs.

```text
POST /api/member/ws-ticket        (authenticated HTTP, optional {"event_id"})
  → { "ticket": "ticket.<base64url>", "expires_in": 45 }

new WebSocket(url, ["tz-session", ticket])
```

The ticket is random 128-bit, base64url encoded (a legal subprotocol token),
valid 45 seconds, **single use** (burned on sight, valid or not), and optionally
bound to one event id. It stands for a credential held server-side in
`ws_tickets`; that credential never leaves the database. The previous paths —
control-plane session token as subprotocol, and the member cookie — still work,
so nothing that exists today breaks.

## Freshness hierarchy

Sockets are an optimisation of freshness, not a source of truth. Render warns
that socket connections die during deploys and instance replacement.

1. socket connected → push updates
2. socket dropped → polling resumes
3. socket reconnected → refetch canonical state, reconcile, resume push

## Known limitation: single-instance fan-out

Fan-out goes through the SQLite outbox inside one instance. With more than one
Render instance, a score update handled by instance 1 will not reach a viewer
whose socket landed on instance 2. Shared pub/sub (Redis or a managed realtime
layer) is a prerequisite for horizontal scaling and is **not** part of this
change.

## This is not "production streaming"

The deployment stays `TZ_ENV=demo` with demo live media, fake UGC and photo
storage and demo XRPL. What this change delivers is a publicly functional
real-time application-control channel — a different, earlier milestone.
