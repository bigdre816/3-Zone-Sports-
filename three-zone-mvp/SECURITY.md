# Security model and launch gates

## Authorization principle

The player is never the authority. Every playback path is decided by the control
plane twice:

1. `POST /api/events/{id}/playback-session` evaluates account state, subscription,
   zone, package, destination, lifecycle status, rights version, and the time
   window. On success it issues a short-lived HMAC lease delivered as an
   **HTTP-only, event-path, SameSite=Strict** cookie. No bearer token appears in
   any media URL.
2. The media route (and `POST /api/leases/validate` for an external media proxy)
   re-runs the same decision on every request. A revoked or re-versioned rights
   object, a closed window, or a lifecycle change invalidates the lease
   immediately with `403`, independent of any socket notification.

Socket `rights.revoked` broadcasts only make revocation *faster*; they are not
the enforcement point.

## Token design

`<b64url(payload)>.<b64url(hmac_sha256)>`, unpadded. Every token carries a `typ`
(`session` | `lease` | `ingest`) and `exp`, checked in constant time on verify.
A session token cannot be replayed as a lease or ingest credential; ingest
tokens are additionally scoped to a single `event_id` and `source`.

## WebSocket threat model

| Threat | Mitigation |
| --- | --- |
| Cross-site socket hijack | `Origin` checked against `TZ_ALLOWED_ORIGINS`; connection closed `1008` if not allowed |
| Token in URL / logs | Session token carried in `Sec-WebSocket-Protocol`, never the path/query; access logs record method+path+status only |
| Unauthenticated subscribe | Token verified and zone-checked before the socket is registered |
| Memory/CPU exhaustion | `max_size` message cap, per-connection message rate limit, per-IP connection limit |
| Dead/half-open connections | library ping/pong with timeout; clean shutdown on SIGINT/SIGTERM |
| Stale authorization | `renew` re-evaluates access against live state; media route re-checks on every request |

## HTTP hardening

- Exact-origin CORS with credentials (never `*` when credentials are allowed).
- `Content-Security-Policy: default-src 'none'` with `self` script/style/media,
  `connect-src` limited to self and the configured socket origin; no inline
  script or style is used.
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on API and media.
- Bounded request bodies; disallowed cross-origin requests rejected before work.

## Production launch gates

`TZ_ENV=production` refuses the demo secrets and short/duplicate keys. Before any
public exposure:

- Set a unique `TZ_TOKEN_SECRET` (≥32 chars) and a separate `TZ_MEDIA_SERVICE_KEY`.
- Terminate TLS; serve the socket over `wss://` behind the same allowlist.
- Replace the HMAC demo session with OIDC/OAuth (authorization-code flow, short
  access tokens, refresh rotation).
- Replace the in-memory socket registry with Redis/NATS/Kafka fan-out plus
  per-instance limits; keep the transactional outbox.
- Move state to Postgres with immutable rights versions and an outbox.
- Serve media through managed HLS/DASH packaging with signed cookies/headers at
  the CDN edge; keep the `validate_lease` contract at the edge.
- Store ingest credentials in a secrets manager, scoped per assignment.
- Ship audit to a WORM/append-only sink with operator identity and alerting.
- Add gateway rate limits per account/IP/event, observability, load tests, DR,
  a privacy review for youth content, and counsel-reviewed rights workflows.

## Reporting

This is a pilot. Do not expose it to the public internet without the gates above.
