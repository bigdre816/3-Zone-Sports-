# Run tonight — Cloudflare live rail (or local fake)

This is the operator runbook for the hosted media rail. Default `TZ_LIVE_MEDIA_PROVIDER=demo` (legacy alias `TZ_MEDIA_PROVIDER=demo`) keeps the local MP4 + encoder-heartbeat path working. Member-network uploads stay on `TZ_UGC_MEDIA_PROVIDER=fake` unless you opt into Stream TUS/clips. Cloudflare Stream is the first real hosted rail. These steps were verified against the **fake/demo provider** in tests; a real Cloudflare broadcast is **not** claimed here unless you have filled in live credentials and watched a real ingest.

The player is never the authority. HLS URLs are issued only after Three-Zone PDP (`request_playback` / `validate_lease`). Viewer heartbeats are sent by the **authenticated member/session**, not by an operator.

## Landed on main (publication readiness)

The mastery guide + Cloudflare HLS + settlement stack (PRs #13/#14) ships to `main` via the live-publication readiness branch. Before flipping `TZ_LIVE_MEDIA_PROVIDER=cloudflare`:

```bash
python scripts/live_readiness.py
# or GET /api/ops/live-readiness as an operator
```

Required for a **real** Stream Live publish (not demo):

1. Valid Stream API token (`CLOUDFLARE` or `TZ_CLOUDFLARE_API_TOKEN`)
2. `TZ_CLOUDFLARE_ACCOUNT_ID`
3. `TZ_CLOUDFLARE_CUSTOMER_CODE` (customer subdomain for signed HLS)
4. `TZ_CLOUDFLARE_WEBHOOK_SECRET` matching the Stream webhook header
5. Exact `TZ_CLOUDFLARE_ALLOWED_ORIGINS` / `TZ_PUBLIC_BASE_URL` (https in production)

A Cursor secret named only `CLOUDFLARE` with a bare token is not enough — account id, customer code, and webhook secret must also be set. Prefer one JSON `CLOUDFLARE` secret with all four fields.

## Cloudflare prerequisites

- A Cloudflare account with Stream Live enabled
- Account ID, API token (Stream write), customer subdomain code
- A webhook secret you will paste into Stream **and** `TZ_CLOUDFLARE_WEBHOOK_SECRET`
- Exact playback origins (no `*` in production)
- Authorized footage only

A Cursor Cloud environment secret named `CLOUDFLARE` is accepted as the API token.
One JSON secret also works:

```json
{"account_id":"...","api_token":"...","customer_code":"...","webhook_secret":"..."}
```

Stream still needs account id, customer code, and webhook secret (separate secrets or that JSON). `TZ_LIVE_MEDIA_PROVIDER=cloudflare` (or legacy `TZ_MEDIA_PROVIDER=cloudflare`) must be set or Provision stays on the demo rail. Environment secrets apply to **new** agents only.

Cloud Agent `start` (`.cursor/scripts/cloud-agent-start.sh`) sets `TZ_LIVE_MEDIA_PROVIDER=cloudflare` automatically when those four credentials are all present and the provider is otherwise unset. Incomplete secrets stay on demo so boot does not fail closed into a crash. A Cursor secret named only `CLOUDFLARE` that is not a valid Stream API token is not enough.

Placeholders (copy from `config.example.env`, never commit real secrets):

```bash
export TZ_LIVE_MEDIA_PROVIDER=cloudflare
export TZ_PUBLIC_BASE_URL=https://your.example
export TZ_CLOUDFLARE_ACCOUNT_ID=your-account-id
export TZ_CLOUDFLARE_API_TOKEN=your-api-token
export TZ_CLOUDFLARE_CUSTOMER_CODE=your-customer-code
export TZ_CLOUDFLARE_WEBHOOK_SECRET=your-webhook-secret
export TZ_CLOUDFLARE_ALLOWED_ORIGINS=https://your.example
export TZ_PLAYBACK_LEASE_SECONDS=60
export TZ_VIEWER_HEARTBEAT_INTERVAL_SECONDS=15
export TZ_VIEWER_STALE_AFTER_SECONDS=90
export TZ_XRPL_MODE=demo
```

Production refuses Cloudflare without account/token/customer/webhook secret, live XRPL without complete signing config, and wildcard origins.

## Start command (demo rail — works tonight without Cloudflare)

```bash
cd three-zone-mvp
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
TZ_LIVE_MEDIA_PROVIDER=demo \
TZ_CLOUDFLARE_WEBHOOK_SECRET=local-demo-webhook-secret \
TZ_ALLOWED_ORIGINS=http://127.0.0.1:8000 \
python run.py
```

Open:

- Member site: <http://127.0.0.1:8000> — `demo-viewer` / `change-me-viewer-local`
- Control plane: <http://127.0.0.1:8000/ops> — `demo-owner` / `change-me-owner-local`

## OBS / Larix (real Cloudflare only)

1. Sign in on `/ops` as an operator. Select a **green** event (rights + production path). Click **Provision**.
2. Copy `ingest_url` + `stream_key` once. They are not stored and will not appear again (use **Rotate key** if lost).
3. OBS: Settings → Stream → Custom → Server = RTMPS URL, Stream key = the one-time key. Start streaming.
4. Phone (Larix): RTMPS URL + key. Keep the device awake.
5. Point the Cloudflare Stream webhook at `POST {TZ_PUBLIC_BASE_URL}/api/media/webhooks/cloudflare` with header `X-Webhook-Secret` matching env.
6. `connected` promotes **green → live** only when active rights exist. Yellow/gray/scheduled never auto-start.

## Webhook curl for the local fake

With `TZ_LIVE_MEDIA_PROVIDER=demo` and `TZ_CLOUDFLARE_WEBHOOK_SECRET=local-demo-webhook-secret`, after **Provision** on a green event (note the returned `input_id`):

```bash
curl -sS -X POST http://127.0.0.1:8000/api/media/webhooks/cloudflare \
  -H 'Content-Type: application/json' \
  -H 'X-Webhook-Secret: local-demo-webhook-secret' \
  -d '{"eventType":"connected","timestamp":"local-1","data":{"liveInput":"demo-input-evt_mw_hockey"}}'
```

Use the `input_id` from provision, not a guess. Unknown inputs are ignored and audited. Repeat the same body: idempotent (duplicate).

## Viewer login and playback

1. Member signs in on `/` (or staff watches from `/ops` → Player).
2. Open a **live** or **replay** event they are entitled to.
3. Three-Zone issues a ≤60s lease. HLS (Cloudflare) or local MP4 (demo) is attached only after that check. `lease_token` never appears in JSON to JavaScript.
4. The player starts a view session and sends a 15s heartbeat while `playing` and the page is visible. Duplicate seq is idempotent; large gaps are capped.
5. On `rights.revoked` the player stops and unloads. Heartbeats then fail. A signed HLS URL may still drain until token expiry — that is not the kill switch.

## Stop, sync replay, manifest + digest

1. Operator: **End stream** (or media service `X-Media-Service-Key`). Live becomes replay. If a hosted input was bound, UI shows **recording pending** until the provider reports a ready video id.
2. **Sync** pulls provider status and writes an analytics snapshot (Cloudflare minutes vs Three-Zone qualified seconds). Unavailable provider data is `PROVIDER_DATA_PENDING`. Three-Zone history is never overwritten.
3. `GET /api/events/{id}/settlement-manifest` (operator) closes stale sessions, SHA-256s canonical session records, builds a Merkle root, and enqueues XRPL with **only** the settlement digest + Merkle root.
4. School audit (operator/owner, or `auditor` whose `properties` JSON includes the `property_id`):

   - `GET /api/properties/{property_id}/settlements`
   - `GET /api/properties/{property_id}/settlements/{sid}`
   - `GET /api/properties/{property_id}/settlements/{sid}/sessions` (pseudonyms only)
   - `GET /api/properties/{property_id}/settlements/{sid}/sessions/{session_id}/proof`
   - `POST /api/properties/{property_id}/settlements/{sid}/verify` → `MATCH|MISMATCH|INCOMPLETE|PENDING_PUBLICATION`

Demo XRPL receipts use a `DEMO-` prefix and `simulated=1`. Submitted is never treated as validated. Retry republishes the same commitment.

Seeded Midwest events attach to Lincoln High (`school_lincoln`); Lakeside volleyball uses `school_lakeside`.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Provision 409 `already_provisioned` | One live input per event. Rotate key instead. |
| Webhook does not go live | Event must be **green** (or already live) with active rights. Yellow never auto-starts. Secret header must match. |
| Playback 403 | Zone/package/rights/window/lease. HLS is not issued before PDP. |
| Recording pending stuck | Click **Sync**. Fake provider: tests call `mark_replay_ready`; Cloudflare must finish VOD. |
| Heartbeats 401/403 | Viewer must send Bearer session or member cookie. Operators do not substitute for the member. |
| Verify `MISMATCH` | Do not repair silently. Re-export the original manifest; mutated leaves fail on purpose. |
| Wildcard origin refused | Set exact `TZ_CLOUDFLARE_ALLOWED_ORIGINS`. |
| Secrets in logs | Stream keys, CF API tokens, lease tokens, and `TZ_XRPL_SIGNING_SECRET` must never appear in public config, audit JSON, or fixtures. |

## Tests

```bash
cd three-zone-mvp
python -m compileall -q backend run.py
python -m unittest discover -s tests -v
```

Pipeline coverage lives in `tests/test_media_pipeline.py` (fake provider only).
