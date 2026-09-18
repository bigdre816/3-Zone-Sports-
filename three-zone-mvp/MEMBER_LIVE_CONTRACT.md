# Member live contract (Lovable handshake)

Plane: Three-Zone Runtime. Constitution: fail closed, rights bind the session,
dates are provenance-only. This is the application-control channel, not
production media streaming. Demo env stays `TZ_ENV=demo`.

Live push is **single-instance scoped**. A viewer on Render instance 2 will not
see an update produced on instance 1 until a shared pub/sub exists. Not in this
pass.

## Config

`GET /api/config` (no auth) returns:

```json
{
  "ws_enabled": true,
  "ws_url_base": "wss://<api-host>/ws/events/"
}
```

`ws_url_base` is the API host that served the request (Render), never
`0.0.0.0` and never the GitHub Pages marketing origin.

Cross-origin Lovable must be listed exactly on Render `TZ_ALLOWED_ORIGINS`
(credentialed CORS cannot use `*`). Production allowlist includes
`https://threezonesport.lovable.app` and the preview origin
`https://id-preview--e1c1692a-52f7-4996-b306-bb996baa123b.lovable.app`.
`TZ_PUBLIC_APP_URL=https://threezonesport.lovable.app` is the member portal;
the API and `/ops` stay on `https://three-zone-sports-1.onrender.com`.
Login returns `session_token`; send `Authorization: Bearer <session_token>` on
every HTTP call. The `tz_member_session` cookie is `SameSite=Lax` and will not
ride along from a Lovable origin.

## Ticket handshake

```text
POST /api/member/ws-ticket
Authorization: Bearer <session_token>
{ "event_id": "evt_..." }   or   { "party_id": "party_..." }

→ { "ticket": "<base64url>", "expires_in": 45, "ws_url": "wss://…/ws/events/evt_…" }
```

Connect:

```js
new WebSocket(ws_url, ["tz-session", "ticket." + ticket])
```

- Single-use, 45s TTL, bound to the member and the event/party.
- Burned on a successful handshake. Replay, expiry, and target mismatch close `1008`.
- The long-lived session token is rejected on the handshake.
- Same-origin cookie fallback remains for the in-repo member site only.

## Socket messages

| type | when |
| --- | --- |
| `event.state` | snapshot on connect (scoreboard, status, replay_pending) |
| `score.update` | operator scoreboard write |
| `rights.revoked` | stop playback immediately |
| `rights.restored` | new rights version; caller must re-open |
| `moment.published` | detected score moment |
| `feed.heartbeat` | ingest source health |
| `lease.status` | reply to `{ "type": "renew" }` |
| `pong` | reply to `{ "type": "ping" }` |

## Freshness hierarchy

1. Socket connected → apply push immediately.
2. Socket drops → poll canonical state (2s while watching, 5s live list, 20s feed).
3. Socket reconnects → refetch canonical state, then resume push. Replace snapshots; do not double-count.

`GET /api/events/{event_id}` and `GET /api/member/live` are the canonical HTTP reads.

## Points

`GET /api/member/me` includes:

```json
"points": { "total": 0, "rule_version": "TZ-POINTS-2026.1" }
```

`total` is the sum of `counted` ledger rows. The Me dashboard must not estimate.

| event | amount |
| --- | --- |
| `post.published` | 10 |
| `clip.published` | 15 |
| `game.completed` | 25 |
| `reaction.received` | 2 |

Self-likes are excluded. One counted award per `(actor, subject)` for reactions.
Unlike writes a reversal row. Awards from suspicious accounts are `held`.
Changing a rule later never rewrites history.

## Out of this pass

Multi-instance fan-out, watch-party chat over the push channel, live Cloudflare
media, production XRPL.
