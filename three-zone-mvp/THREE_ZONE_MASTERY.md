# Three Zone Mastery

**The complete plain-English map of everything that lives in this system.**

This is not a marketing page. It is the owner’s master document: the vision, every engine, every API, every connection, every table, every token, every cookie, every audit event, the Treasure verification path, and the blockchain (XRPL) publication chain. Print it from the owner back portal (Owner → Mastery → Print this guide), or open `/three-zone-mastery` and print the page.

If a piece of the live site is currently running, the Owner → Inventory report prints the **live numbers**. This document prints the **meaning** of those numbers.

---

## How to print this

1. Sign in on `/ops` as `demo-owner` / `change-me-owner-local` (or your real owner account).
2. Open the **Owner** dropdown in the left sidebar.
3. Click **Mastery**.
4. Click **Print this guide**. Your browser print dialog will produce a black-on-white paper copy.
5. Separately, Owner → Inventory → **Print everything** prints the live users, events, rights versions, analytics, and audit log.

The source file of this article is `three-zone-mvp/THREE_ZONE_MASTERY.md` in the repository.

---

## 1. What this repository actually is

The git repository is named **The-system**. It holds two related products, plus a leftover clock page.

**Product A — Moten IP & Invention Control Plane** (`index.html` at the repo root). A browser-only confidential control surface for invention work. It uses local storage. It is a prototype of the Moten master specification: research registry, invention ledger, disclosure firewall, filing calendar, counsel workbench, evidence hashes, default-deny access, AI gateway, rights registry, lease simulation, socket simulation, ingest, revocation, discovery, measurement, settlement, partner adapters, WORM export, and drills. It does **not** serve live sports video. It is the **IP and policy brain** of the larger idea.

**Product B — Three-Zone control-plane MVP** (`three-zone-mvp/`). A runnable Python server. This is the **event-to-media machine**: catalog, rights, entitlement, playback leases, replay, member site, operator console, owner back portal, Treasure verification adapter, hashed audit chain, and a simulated XRPL (XRP Ledger) publication path. This is what you log into at `/` and `/ops`.

**Leftover —** `timezone-clock.html` is a decorative multi-timezone clock. It is not wired into Three-Zone or Moten.

When this document says “the system,” it means Product B unless it explicitly says Moten IP.

The machine in one sentence:

**A camera or encoder may only become a family playback if Three-Zone says the event is real, the rights are active, the viewer is entitled, a short lease is issued, and the media path re-checks that same decision on every byte.**

The loop:

```text
camera / encoder signal
  → authorized event (lifecycle + rights + production heartbeat)
    → family playback (lease + cookie + media re-check)
      → automatic replay
        → archive
          → hashed audit record
            → blockchain (XRPL) publication of the hash, not the private payload
```

---

## 2. The vision, in plain English

Three-Zone is not “a sports website.” It is a **rights-aware distribution machine** for school and community sports, designed so a family can watch what they are entitled to, and so nobody else can.

The Moten invention ledger names six Three-Zone families and six Treasure families. Those are the mechanisms this MVP is proving in software, even when a given family is still a simulation.

### 2.1 The six Three-Zone invention families

**TZ-01 — Rights-aware distribution router.** Join household relationship, service area, package, rights, territory, device, and destination, then route only to an authorized experience. In this MVP the router is `evaluate_access`: account, subscription, zone, package, destination, lifecycle, and time window.

**TZ-02 — Demand-guided rights acquisition engine.** Join demand to versioned property availability, rights expiry, production readiness, and economics, then emit a ranked opportunity with a human approval gate. This MVP does **not** yet rank acquisition opportunities. It does keep rights versioned and production-gated, which is the constraint side of that engine.

**TZ-03 — Adaptive broadcast orchestration.** Choose ingest, certified producer, or full-service broadcast from rights, feed quality, local capability, cost, and reliability. This MVP implements the **ingest and failover** slice: primary/backup heartbeats, timeout failover, and return to primary.

**TZ-04 — Rights-bound media object.** Every media derivative should carry territory, window, replay, clips, ads, master, distributor, expiration, and authorization. This MVP binds a lease to `event_id`, `rights_version`, `mode`, and `sub`, then re-validates on the media path. The local MP4 is a stand-in for a packaged object.

**TZ-05 — Auditable multi-property settlement.** Compute economics from immutable measurement facts and formula versions. This MVP does **not** compute money. It does keep an append-only audit and a hash-chained `audit_events` table so settlement later has a reconstructible history.

**TZ-06 — Relationship-based sports discovery graph.** Navigate from family, school, hometown, alumni, conference, or team to rights-aware availability. This MVP has schools, teams, schedules, archives, and a search that only returns authorized catalog items. It is not yet a full relationship graph.

### 2.2 The six Treasure invention families

Treasure is the **verification and evidence** side. It is not the sports player.

**TR-01 — Reward / evidence separation.** Rewards a bounded activity without rewriting evidence history. Independent ledgers and signed event references. In this MVP, the operational `audit` table and the canonical `audit_events` hash chain are separate from any future reward score.

**TR-02 — Capped score impact with persistent evidence.** Not implemented as a score product here. The principle is already visible: evidence accumulates even when access is denied.

**TR-03 — Multi-activity consistency history.** Canonical audit events keep type, actor, subject, payload hash, and previous hash so different activities stay distinguishable.

**TR-04 — Participant-selected evidence presentation.** Not a member-facing evidence wallet yet. Operator/owner can inspect an audit event and its XRPL receipt without dumping private media.

**TR-05 — AI-assisted control architecture.** Moten IP’s AI gateway is the prototype. Three-Zone itself does not call an AI. Humans and policy remain the authority.

**TR-06 — Anonymous-to-authorized identity transition.** Member login starts as a username/password, then **Treasure verification** issues a time-bounded VERIFIED record before a member session cookie is set. In demo, Treasure is simulated. In production, missing Treasure is fail-closed.

### 2.3 The Moten IP control plane (root `index.html`)

That browser app is the confidential invention office: command center, research registry with immutable question versions, invention ledger, human contribution capture (AI is tool-only), disclosure firewall (hold/file-first), USPTO filing calendar, counsel workbench, SHA-256 manifests, default-deny access, AI gateway, provisional support matrix, rights registry, policy decision point, short-lived rights leases, live-socket admission simulation, ingest qualification, revocation propagation, discovery graph, privacy-bounded measurement, settlement recalculation, partner adapter allowlist, WORM/legal-hold export, and 12-month drills.

It is **not** production WORM, KMS, identity, gateway, or SIEM. It is the map of what Three-Zone must never contradict.

### 2.4 The blockchain, named clearly

The blockchain in this system is the **XRP Ledger (XRPL)**.

Three-Zone does **not** put video on a chain. It does **not** put passwords, leases, or family identity on a chain. It writes a **canonical audit event** first (hash-chained, append-only, in SQLite). Then a publisher may submit a **hash manifest** of that audit event to XRPL so a third party can later prove “this operational record existed and has not been rewritten.”

In demo/local, XRPL publication is **simulated**: a fake transaction id `DEMO-` plus a hex prefix, status `VALIDATED`, flag `simulated=1`. The test `test_audit_persists_before_simulated_xrpl_receipt` locks the order: **audit first, chain receipt second**.

In `TZ_ENV=production`, the process **refuses to start** unless XRPL settings are complete: RPC URL, network, audit account, signing secret, and key id. The live XRPL submit client is **not yet implemented**; the tables, hashes, config gate, and simulated publisher are in place so the contract is visible.

That is the blocked chain / blockchain path, end to end, as it exists today.

---

## 3. The one law: the player is never the authority

The browser video tag cannot decide if you may watch. Neither can a WebSocket message.

Authorization happens twice:

1. **Issue time.** `request_playback` (member path or ops path) evaluates the live event and rights. On success it issues a short HMAC **lease**. The lease token is delivered as an HTTP-only cookie scoped to that media path. The media URL itself has **no bearer token**.
2. **Serve time.** Every request to `/demo/media/{event_id}.mp4` (and `/api/leases/validate` for a future CDN) re-runs `validate_lease`. If rights were revoked, re-versioned, the window closed, the account died, or the token was tampered, the answer is 403.

A socket `rights.revoked` message only makes the UI stop faster. It is not enforcement.

If you remember one sentence from this entire document, remember that.

---

## 4. The three sides of the website

| Side | Role in the database | Demo account | Password (local/demo only) | Where you land |
| --- | --- | --- | --- | --- |
| Member site | `viewer` | `demo-viewer` | `change-me-viewer-local` | `/` |
| Back worker | `operator` | `demo-worker` | `change-me-worker-local` | `/ops` |
| Owner back portal | `owner` | `demo-owner` | `change-me-owner-local` | `/ops` |

Override those passwords with `TZ_SEED_PASSWORD_VIEWER`, `TZ_SEED_PASSWORD_WORKER`, `TZ_SEED_PASSWORD_OWNER`. Production refuses the demo values.

**Members** see only entitled zones and packages. They watch live and replay. They cannot create events, revoke rights, import schedules, or open inventory.

**Workers** run production: create events, move lifecycle, scoreboard, ingest tokens, revoke/restore rights, schedules, analytics, audit. They cannot open the owner inventory or this Mastery print if we gate it owner-only.

**Owners** can do everything a worker can, plus print/export the whole site and print this mastery guide.

Staff cannot self-register. `POST /api/auth/register` always creates a **viewer** with midwest / standard / web. Usernames `demo-owner`, `demo-worker`, `demo-admin`, `owner`, `operator`, `admin`, `root`, `system` are reserved.

A signed-in worker or owner on `/` sees a **Control plane** link. `/ops` has a **Member site** link. That is how you move without editing the URL.

---

## 5. How the two processes start

`python run.py` does this:

1. Read configuration from the environment (`Config.from_env`).
2. Open SQLite at `TZ_DATABASE_PATH` (default `data/three_zone.sqlite3`).
3. Create every table if missing. Add `password_hash` with `ALTER TABLE` on old databases.
4. Seed demo users always (upsert). Seed demo events only if the events table is empty.
5. Start a **separate WebSocket process** (`multiprocessing`, daemon) sharing the same SQLite file in WAL mode.
6. Serve HTTP in the parent process (`ThreadingHTTPServer`).
7. On Ctrl-C, shut down HTTP, terminate the WS process, close the database.

Default bind: HTTP `http://127.0.0.1:8000`, WebSocket `ws://127.0.0.1:8765/ws/events/<event_id>`.

Only third-party Python package: `websockets`. Everything else is the standard library. FFmpeg is optional, used only to generate a nicer demo MP4.

Docker image runs `TZ_ENV=production` and therefore **refuses demo secrets**. You must pass real `TZ_TOKEN_SECRET`, `TZ_MEDIA_SERVICE_KEY`, `TZ_ALLOWED_ORIGINS`, seed passwords, and complete XRPL config.

---

## 6. Sign-in, registration, sessions, and cookies

There are **two session systems** on purpose.

### 6.1 Control-plane session (Bearer token)

Used by `/ops` and most `/api/*` routes.

- Format: HMAC token type `session`, claim `sub` = `user_id`, TTL `TZ_SESSION_TTL` (default 3600 seconds).
- Stored in `sessionStorage` as `tz_session`.
- Sent as `Authorization: Bearer <token>`.
- Created by password login, register, or demo-login.

### 6.2 Member session (HTTP-only cookie)

Used by member APIs (`/api/member/*`).

- Cookie name: `tz_member_session`
- Path `/`, `HttpOnly`, `SameSite=Strict`, Max-Age = session TTL
- Value is a `SES-…` id in table `member_sessions`
- Bound to a Treasure `verification_id`
- Created by `PortalService.complete_auth` after login/register/verify

Password login and register call `complete_auth`, so **both** the Bearer token and the member cookie are issued. That is why a new member can watch immediately, and why an owner can open Member site without logging in twice.

Logout: `POST /api/auth/logout` revokes the member session row and clears the cookie. The ops UI also drops `tz_session` from `sessionStorage`.

### 6.3 Password engine

File: `backend/passwords.py`.

- Hash: `pbkdf2$sha256$210000$<salt hex>$<digest hex>`
- 16 random bytes of salt, 210,000 iterations, SHA-256, constant-time compare
- Username: lowercase, regex `^[a-z0-9][a-z0-9_-]{2,31}$`
- Password: 8 to 128 characters
- Wrong password and unknown user both return the same 401 `invalid_credentials`
- Suspended accounts (`account_state != active`) return 403 `account_suspended`

### 6.4 Demo login (tests and old clients)

`POST /api/auth/demo-login` with `{ "account": "demo-viewer" | "demo-worker" | "demo-owner" }` still works. The member UI no longer uses it.

### 6.5 Treasure-backed verify (older member path)

`POST /api/auth/start` then `POST /api/auth/verify` still exist. Start maps unknown identifiers to `demo-viewer` except `andre`. Verify runs Treasure simulation and sets the member cookie. This is the anonymous-to-authorized path for the older “Verify and enter” flow.

---

## 7. The event engine and lifecycle

An **event** is one game (or other show) the control plane owns.

Lifecycle, in order, no skipping:

`scheduled → gray → yellow → green → live → replay → archive`

Allowed next states are hard-coded. Jumping `scheduled` to `live` is `illegal_transition` (409).

**Guards:**

- To enter **yellow**, a rights object must exist.
- To enter **green** or **live**, active (non-revoked) rights must exist **and** a **fresh production heartbeat** must exist on the effective source (primary or backup). That is `production_not_ready` if the encoder has not checked in within `TZ_HEARTBEAT_TIMEOUT` seconds (default 12).
- **live → replay** can be done by an operator transition, or automatically by the media service calling `POST /api/events/{id}/media/end` with header `X-Media-Service-Key`. Only a live event can end this way (`not_live`). Replay sets `replay_available=1`.
- **archive** is terminal.

Production modes stored on the event: `single_camera`, `multi_camera`, `backup_active`.

Zones: `midwest`, `west`, `east`. Create-event rejects any other zone (`bad_zone`).

Scoreboard is a JSON object on the event: typically `home`, `away`, `period`, `clock`. Updating it writes audit `event.score` and socket `score.update`.

---

## 8. The rights engine

Rights are **versioned**. They are never silently edited in place for a restore.

Each rights row includes: event_id, version, territory, destination, package, live_start, live_end, replay_start, replay_end, authority, source_reference, active, revoked, revocation_reason, archive_retention_days (default 365), created_at. Unique on `(event_id, version)`.

**Current rights** = highest version that is `active=1` and `revoked=0`.

**Revoke:** mark that row `active=0`, `revoked=1`, store a reason. Socket `rights.revoked`. Existing leases fail on next media check (`rights_unavailable` or, after restore, `rights_version_changed`).

**Restore:** insert a **new** version copied from the latest historical row. Old revoked rows remain forever. Owner inventory prints every version.

Creating an event always inserts rights version 1: territory = zone, destination default `web`, package default `standard`, live window start→+3 hours, replay window start→+30 days, authority = operator display name, source_reference `contract://{event_id}`.

Seeded events use authority **State Athletic Association**.

---

## 9. The entitlement engine (policy decision point)

`ControlPlane.evaluate_access(user, event_row, mode=None)` is pure. It does not issue tokens. It returns allow/deny plus a public subset that does not leak extra reasons.

Checks, in order:

1. `account_state` must be `active` else `account_suspended`
2. `subscription` must be `active` else `subscription_inactive`
3. User zones must include the event zone, or `*` else `zone_not_entitled`
4. Active rights must exist else `rights_unavailable`
5. User packages must include the rights package, or `*` else `package_not_entitled`
6. User destinations must include the rights destination, or `*` else `destination_not_allowed`
7. Event status must be `live`, `replay`, or `archive` else `not_playable` (green/yellow/gray/scheduled are not playable)
8. Optional `mode` must match the resolved mode else `mode_mismatch`
9. Current time must fall inside the live window (for live) or replay window (for replay/archive) else `window_not_open` / `window_closed`

demo-viewer: zones `[midwest]`, packages `[standard]`, destinations `[web]`. West/East events are denied.

demo-worker and demo-owner: zones/packages/destinations `["*"]`.

---

## 10. The playback lease engine

On allow, `request_playback` signs a token type `lease` with claims:

- `sub` — user_id
- `event_id`
- `rights_version`
- `mode` — live | replay | archive
- `lease_id` — random hex
- `typ`, `iat`, `exp`

TTL: `TZ_LEASE_TTL` (default **90 seconds**). Short on purpose.

HTTP handler **strips `lease_token` from JSON** and sets cookie:

`tz_lease_{event_id}=<token>; Path=/demo/media/{event_id}.mp4; Max-Age=<lease_ttl>; HttpOnly; SameSite=Strict`

JSON still returns `allow`, `mode`, `rights_version`, `lease_id`, `lease_ttl`, `media_url`.

`validate_lease` checks signature, type, expiry, event match, subject exists, event exists, `evaluate_access` with the bound mode, and **exact rights_version match**.

Member playback also inserts `lease_records` and writes canonical audit `lease.issued` (and `playback.requested` / `lease.denied`).

---

## 11. The media engine (replacement seam)

File: `backend/demo_media.py`.

This is **not** production video. It generates a small local MP4 (FFmpeg testsrc color bars if FFmpeg exists, otherwise a tiny structurally valid MP4 that may not render). Path: `{database_dir}/media/{event_id}.mp4`.

`GET /demo/media/{event_id}.mp4`:

1. Read cookie `tz_lease_{event_id}`
2. If missing → 403 `no_lease`
3. `validate_lease` → 403 on failure
4. Honor HTTP `Range` (206 partial, 416 unsatisfiable) so the browser can seek
5. `Cache-Control: no-store`

Production replacement: SRT contribution → transcoder → packager → object store → CDN. The CDN edge must call `POST /api/leases/validate` with `X-Media-Service-Key`. That key is **separate** from `TZ_TOKEN_SECRET`. Constant-time compare. Wrong key → 403 `bad_service_key`.

`POST /api/events/{id}/media/end` uses the same service key to flip live → replay.

---

## 12. Ingest, heartbeat, and failover

Operators issue an **ingest token** (type `ingest`) scoped to one `event_id` and one `source` (`primary` or `backup`), plus a unique `jti`. TTL `TZ_INGEST_TTL` (default 6 hours).

The encoder (example script `scripts/ingest_heartbeat.py`) POSTs:

`/api/events/{id}/ingest/heartbeat` with `{ ingest_token, source, healthy }`

The token must match event **and** source (`ingest_scope`).

If `healthy` is true, `primary_last_seen` or `backup_last_seen` is stamped now. If false, last-seen is not updated (it goes stale).

**Effective source:** prefer a fresh primary; else a fresh backup; else keep the stored `active_source`. Fresh means last-seen within `heartbeat_timeout`.

When effective source changes, audit `feed.failover` and socket `feed.heartbeat`.

The WebSocket process also runs a **feed_loop** every 2 seconds on green/live events to detect timeout failover even if no new heartbeat arrives.

Without a fresh heartbeat, the event cannot go green or live.

---

## 13. The live socket engine

Separate process. Path: `ws://{host}:{ws_port}/ws/events/{event_id}`

**Admission:**

- `Origin` must be in `TZ_ALLOWED_ORIGINS` or the handshake is closed 1008
- Path must start `/ws/events/`
- Session token must be offered in `Sec-WebSocket-Protocol` as a value **other than** the dummy `tz-session` (the browser sends `["tz-session", token]` so the dummy is the named subprotocol)
- Token must verify as type `session`
- Event must exist
- User must be zone-entitled
- Per-IP connection cap `TZ` default 20 (`ws_max_conns_per_ip`)
- Max message size 16 KiB
- Per-connection 40 messages / 10 seconds
- Ping/pong every 20s, timeout 20s
- SIGINT/SIGTERM clean shutdown

**On connect:** send `event.state` with a full event snapshot.

**Client messages:** `ping` → `pong`; `renew` → re-run `evaluate_access` and send `lease.status`.

**Fan-out:** HTTP writes `socket_outbox`. WS process polls every 0.3s, broadcasts, marks `delivered=1`.

**Metrics:** every 3s write `socket_metrics` (single row id=1): total connections, per-event counts, updated_at. Analytics treats metrics as fresh if updated within 10 seconds.

Socket types you will see: `event.state`, `score.update`, `feed.heartbeat`, `rights.revoked`, `rights.restored`, `lease.status`, `pong`.

---

## 14. Member site engines (Sports Access)

Pages: `/` (`index.html` + `portal.js` + `styles.css`).

After sign-in: Live, Schedules, Archives, search, Watch. No marketing hero.

**Live** — events in status live, green, or scheduled that the member is zone-entitled to see. Green/scheduled cards still say Watch; playback will fail with a toast if not actually playable.

**Schedules** — versioned fixtures: school, team, opponent, date, location, home/away, season.

**Archives** — `archive_objects` with status ARCHIVED, joined to school and team.

**Search** — schools, teams, and entitled event titles. Minimum 2 characters in the UI.

**Watch** — `POST /api/member/events/{id}/playback` then `<video src="{media_url}?lease={lease_id}">`. The query string is **not** the secret; the cookie is.

Catalog seed (`_ensure_catalog`) uses `INSERT OR IGNORE` so eight tabs hitting live/schedules/archives at once cannot UNIQUE-crash.

Seeded catalog:

- Schools: Lincoln High, Lakeside Prep, Northridge (all midwest)
- Teams: Lincoln Freshman Basketball (freshman basketball), Lakeside Prep Basketball, Northridge Soccer
- Schedule `sch-lincoln-2026` version 1: vs Central Valley (home, Riverside Stadium), vs Maple Grove (away, Lakeside Gym)
- Archive `arc-central-wrestling` → event `evt_mw_wrestling`, title “Central Wrestling — Full Game”

Schedule CSV import (operator) required columns: school, team, sport, level, opponent, date, start time, location, home/away, season. Bad rows rejected; a good file creates a **new version** and keeps the old. Unknown school/team rejected. Duplicate opponent+start rejected. Catalog is seeded first so control-plane import works on a fresh DB.

---

## 15. Treasure verification engine

Treasure is the **identity/evidence verifier**, not the video CDN.

`PortalService.verify_treasure(member_id)`:

- If env is not `demo`, `development`, or `local` → `verification_unavailable` (fail closed)
- Else insert `member_verifications`: status `VERIFIED`, type `member_access`, 1 hour expiry, evidence hash of `{member_id, type, at}`, verifier `treasure-network`, receipt id `TRR-…`, `simulated=1`
- Canonical audit `treasure.verification.completed`

A member session is valid only if that verification is still VERIFIED and unexpired. Revoking the verification row denies playback (`verification_required`).

Internal operator routes (Bearer operator):

- `POST /internal/treasure/verify`
- `POST /internal/treasure/revalidate`

Both currently call the same verify helper.

This is TR-06 in miniature: you do not get a member cookie until verification exists.

---

## 16. The audit chain and the blockchain (XRPL)

There are **two audit ledgers**.

### 16.1 Operational audit (`audit` table)

Simple append-only log the operator UI reads (`GET /api/audit`): id, ts, actor, action, event_id, detail JSON.

Actions include: `auth.login`, `auth.register`, `auth.demo_login`, `event.created`, `event.transition`, `event.score`, `event.media_end`, `rights.revoked`, `rights.restored`, `ingest.token_issued`, `feed.failover`, `playback.granted`, `playback.denied`, `seed.loaded`, plus every portal event type copied through `audit_log`.

### 16.2 Canonical hash-chained audit (`audit_events` table)

This is the legal-grade stream.

Each row:

- `event_id` like `AUD-…` (not a sports event id)
- `event_type`, `entity` (`three-zone`), `source_service` (`three-zone-api`)
- `subject_id`, `actor_type`, `actor_id`
- `occurred_at`, `recorded_at`
- `payload_version` `1.0`
- `payload` JSON, `payload_hash` = `sha256:` + SHA-256 of canonical JSON
- `previous_event_hash` — hash of the previous payload, forming a **hash chain**
- `correlation_id`, `verification_ref`, `rights_version`
- `legal_effect` currently `operational_record`

Portal event types written here: `treasure.verification.completed`, `member.login.requested`, `member.login.denied`, `member.login.success`, `event.discovered`, `playback.requested`, `lease.denied`, `lease.issued`, `schedule.version.created`.

The hash chain means you cannot silently rewrite history without breaking the next `previous_event_hash`. That is the **blocked chain inside the database**.

### 16.3 XRPL publications (`xrpl_publications` table)

`publish_pending()` selects canonical audit events with **no** XRPL row yet, oldest first. For each:

- Build `manifest_hash` = sha256 of `{audit_event_id, payload_hash}`
- In demo: `xrpl_transaction_hash` = `DEMO-` + first 24 hex of sha256(manifest)
- `xrpl_account` = `demo-audit-account`
- `ledger_index` = `simulated-ledger`
- `status` = `VALIDATED`
- `simulated` = 1
- `retry_count` = 0

What is **not** on the ledger: video, cookies, passwords, display names, raw payloads. Only hashes.

Operator inspection: `GET /api/admin/audit/{AUD-…}` and `GET /api/admin/audit/{AUD-…}/xrpl` return the canonical event plus the XRPL receipt if any.

Publisher trigger: `POST /internal/audit/events` (operator) returns `{ publication_ids, simulated: true }`.

Production config required (else process will not start): `XRPL_RPC_URL`, `XRPL_NETWORK`, `XRPL_AUDIT_ACCOUNT`, `XRPL_SIGNING_SECRET`, `XRPL_KEY_ID`. Public `/api/config` never includes the signing secret.

**Honest status:** the hash chain and simulated publisher are real code. A live signed XRPL submit over RPC is the next construction step. Do not claim mainnet settlement from this MVP.

---

## 17. Operator control plane (`/ops`)

Dark operational console. Left sidebar. One pane at a time.

**Catalog** — all events the caller may see (workers/owners: all zones). Filter chips: all, midwest, west, east. Cards show status, zone, category, score, feed pill, Open / Watch replay.

**Player** — lease-gated video, score, feed health, socket log. Select an event from Catalog first.

**Operations dropdown**

- Create event — title, zone, category, production mode
- Event controls — bound to the selected catalog event: next lifecycle button only, revoke/restore, scoreboard, ingest token issue
- Schedule import — CSV preview; malformed rows rejected; new version on correction
- Analytics and audit — JSON analytics + scrolling audit list

**Owner dropdown** (hidden unless role is owner/admin)

- Inventory — load / print everything / download JSON
- Mastery — this document, print in plain English

**Account** — who you are, Member site, Sign out.

Viewers who log in on `/ops` are redirected to `/`.

---

## 18. Owner back portal (print and export)

`GET /api/owner/inventory` requires role owner or admin.

Payload:

- `generated_at`
- `environment` — public config only (no secrets)
- `tiers` — the three-side map
- `routes` — every HTTP and WS path the site admits it has
- `totals` — users, events, rights_versions, audit_entries
- `users` — every user without `password_hash`
- `events` — every event plus **all** rights versions (revoked included)
- `audit` — full operational audit oldest-first
- `analytics` — counts by status/zone and socket metrics

UI: Load full inventory fills a white print document (`#print-root`). Print everything uses `window.print()` with CSS that hides the dark chrome. Download JSON saves `three-zone-inventory-{timestamp}.json`.

Workers hitting this API get 403 `owner_required`.

---

## 19. Every HTTP and WebSocket route

Static pages (public to load; APIs still gated):

| Method | Path | Who | What it is |
| --- | --- | --- | --- |
| GET | `/` | public | Member site |
| GET | `/ops` | public | Control plane console |
| GET | `/portal.js` `/styles.css` | public | Member assets |
| GET | `/app.js` `/ops.css` | public | Ops assets |
| GET | `/favicon.ico` | public | Empty 204 |
| GET | `/three-zone-mastery` | public | Printable HTML of this guide |

Auth and identity:

| Method | Path | Who | What it is |
| --- | --- | --- | --- |
| POST | `/api/auth/login` | public | Username + password; session + member cookie |
| POST | `/api/auth/register` | public | Create viewer only |
| POST | `/api/auth/demo-login` | public | Demo account picker |
| POST | `/api/auth/start` | public | Begin Treasure verify flow |
| POST | `/api/auth/verify` | public | Finish verify; member cookie |
| POST | `/api/auth/logout` | public | Revoke member cookie |
| GET | `/api/me` | session | Control-plane identity |
| GET | `/api/member/me` | member cookie | Member identity + verification ids |
| GET | `/api/health` | public | `{status: ok}` |
| GET | `/api/config` | public | Ports, TTLs, zones; never secrets |

Member:

| Method | Path | Who | What it is |
| --- | --- | --- | --- |
| GET | `/api/member/live` | member | Live/upcoming entitled games |
| GET | `/api/member/schedules` | member | Team fixtures |
| GET | `/api/member/archives` | member | Archive cards |
| GET | `/api/member/search` | member | `?q=` discovery |
| POST | `/api/member/events/{id}/playback` | member | Lease + media cookie |
| POST | `/api/member/archive/{archive_id}/playback` | member | Archive lease if event is archive |

Catalog and playback (ops + shared):

| Method | Path | Who | What it is |
| --- | --- | --- | --- |
| GET | `/api/events` | session | Catalog, zone filtered |
| GET | `/api/events/{id}` | session | Detail + public access decision |
| POST | `/api/events/{id}/playback-session` | session | Ops/member lease |
| GET | `/demo/media/{id}.mp4` | lease cookie | Bytes after re-check |
| POST | `/api/leases/validate` | media service key | CDN/proxy re-check |

Worker:

| Method | Path | Who | What it is |
| --- | --- | --- | --- |
| POST | `/api/events` | operator | Create event + rights v1 |
| POST | `/api/events/{id}/transition` | operator | `{target}` |
| POST | `/api/events/{id}/score` | operator | `{scoreboard}` |
| POST | `/api/events/{id}/rights/revoke` | operator | `{reason}` |
| POST | `/api/events/{id}/rights/restore` | operator | New rights version |
| POST | `/api/events/{id}/ingest-token` | operator | `{source}` |
| POST | `/api/admin/schedules/upload` | operator | `{filename, csv}` |
| GET | `/api/audit` | operator | Operational log |
| GET | `/api/admin/audit/{AUD-id}` | operator | Canonical event + XRPL |
| GET | `/api/admin/audit/{AUD-id}/xrpl` | operator | Same handler |
| POST | `/internal/treasure/verify` | operator | Treasure adapter |
| POST | `/internal/treasure/revalidate` | operator | Same |
| POST | `/internal/audit/events` | operator | Publish pending hashes to XRPL simulator |

Ingest and media service:

| Method | Path | Who | What it is |
| --- | --- | --- | --- |
| POST | `/api/events/{id}/ingest/heartbeat` | ingest token | Encoder health |
| POST | `/api/events/{id}/media/end` | media service key | live → replay |

Owner:

| Method | Path | Who | What it is |
| --- | --- | --- | --- |
| GET | `/api/owner/inventory` | owner | Full live dump |
| GET | `/api/owner/mastery` | owner | `{title, html}` of this guide |
| GET | `/api/analytics` | session | Counts + socket metrics |

Socket:

| Method | Path | Who | What it is |
| --- | --- | --- | --- |
| WS | `/ws/events/{id}` | session subprotocol | Live state fan-out |

Event ids in HTTP paths must match `evt_[a-z0-9_]+`. Canonical audit ids match `AUD-[a-z0-9-]+`.

Bodies larger than 64 KiB → 413 `body_too_large`. Bad JSON → 400 `bad_json`. Unknown path → 404 `not_found`. Disallowed Origin → 403 `forbidden_origin`. Missing Bearer where required → `missing_session`. Uncaught exception → 500 `internal` with no traceback in the body.

---

## 20. Every database table

SQLite, WAL, busy_timeout 5000 ms, foreign_keys ON, one connection with a thread lock.

**users** — user_id (PK), display_name, role (`viewer` | `operator` | `owner` | `admin`), account_state, subscription, zones JSON, packages JSON, destinations JSON, password_hash.

**events** — event_id, title, zone, category, status, scheduled_start, production_mode, active_source, primary_last_seen, backup_last_seen, scoreboard JSON, replay_available, created_at.

**rights** — id, event_id, version, territory, destination, package, live_start, live_end, replay_start, replay_end, authority, source_reference, active, revoked, revocation_reason, archive_retention_days, created_at. UNIQUE(event_id, version).

**audit** — id, ts, actor, action, event_id, detail.

**socket_outbox** — id, event_id, type, payload, created_at, delivered.

**socket_metrics** — id must be 1, connections, per_event JSON, updated_at.

**member_sessions** — session_id, member_id, verification_id, entitlement_version, device_binding, status, issued_at, expires_at, revoked_at.

**member_verifications** — verification_id, member_id, status, verification_type, verified_at, expires_at, evidence_hash, verifier, receipt_id, simulated.

**schools** — school_id, name UNIQUE, territory.

**teams** — team_id, school_id, name, sport, level.

**schedules** — schedule_id, school_id, team_id, season, current_version, status.

**schedule_versions** — schedule_id + version PK, source_type, source_name, source_file_hash, uploaded_by, uploaded_at, effective_at, supersedes_version, status.

**schedule_events** — schedule_id + version + schedule_event_id, opponent, start_at, location, home_away, source_row.

**archive_objects** — archive_id, event_id, school_id, team_id, season, kind, title, thumbnail, status.

**lease_records** — lease_id, event_id, member_id, session_id, rights_version, permitted_use, status, issued_at, hard_expiry, close_reason.

**audit_events** — the hash-chained canonical log (see §16.2).

**xrpl_publications** — publication_id, audit_event_id, payload_hash, manifest_hash, xrpl_account, xrpl_transaction_hash, ledger_index, submitted_at, validated_at, status, error_code, retry_count, simulated.

Indexes: rights by event+version, outbox undelivered, member_sessions by member+status, schedule_events by schedule+version+start, audit_events by subject+occurred_at.

JSON helpers: `dumps` (sorted keys, compact) and `loads`.

---

## 21. Every token type

Format for session, lease, and ingest: `<base64url(json)>.<base64url(hmac_sha256)>`, no padding. HMAC-SHA256 with `TZ_TOKEN_SECRET`. Verify is constant time. Wrong `typ` is rejected. Expiry is unix seconds.

| typ | Bound to | Used for |
| --- | --- | --- |
| session | `sub` | HTTP Bearer and WebSocket subprotocol |
| lease | sub, event_id, rights_version, mode, lease_id | Media cookie |
| ingest | event_id, source, jti | Encoder heartbeat |

Media service key is **not** an HMAC token. It is a shared secret header `X-Media-Service-Key`.

Passwords are PBKDF2, not HMAC tokens.

---

## 22. Every cookie

| Name | Path | Flags | Meaning |
| --- | --- | --- | --- |
| `tz_member_session` | `/` | HttpOnly, SameSite=Strict | Member portal session id |
| `tz_lease_{event_id}` | `/demo/media/{event_id}.mp4` | HttpOnly, SameSite=Strict | Playback lease for that file only |

No token is placed in URLs or server access logs. HTTP `log_message` is a no-op.

Browser `sessionStorage.tz_session` is the ops Bearer token (not a cookie).

---

## 23. Every denial and error code

HTTP mapping: AuthError 401, ForbiddenError 403, NotFoundError 404, ConflictError 409, ValidationError/ControlError 400.

| code | Meaning |
| --- | --- |
| invalid_credentials | Bad username or password |
| bad_username | Invalid or reserved register name |
| bad_password | Password not 8–128 chars |
| username_taken | Register conflict |
| unknown_account | Bad demo-login account |
| account_suspended | User not active |
| invalid_session | Bad/expired/unknown session |
| missing_session | No Bearer token |
| operator_required | Viewer tried a worker route |
| owner_required | Non-owner tried inventory/mastery API |
| event_not_found | Unknown evt_ id |
| zone_not_entitled | Outside the viewer’s zones |
| title_required / bad_zone / bad_state / bad_source / bad_scoreboard | Validation |
| illegal_transition | Lifecycle skip |
| rights_unavailable | Need active rights |
| production_not_ready | No fresh heartbeat |
| not_live | media/end on a non-live event |
| invalid_ingest_token / ingest_scope | Encoder credential wrong |
| bad_service_key | Wrong media service key |
| subscription_inactive | Entitlement |
| package_not_entitled | Entitlement |
| destination_not_allowed | Entitlement |
| not_playable | Status not live/replay/archive |
| mode_mismatch | Lease mode vs live state |
| window_not_open / window_closed | Rights window |
| invalid_lease / event_mismatch / unknown_subject / rights_version_changed | Lease re-check |
| no_lease | Media request without cookie |
| verification_unavailable | Treasure required outside demo |
| member_unavailable | complete_auth unknown user |
| entitlement_denied | Inactive account/subscription at member login |
| verification_required | Member session’s Treasure record dead |
| archive_not_found / archive_not_authorized | Archive playback |
| playback_denied | Member-safe wording for failed lease |
| audit_not_found | Unknown AUD- id |
| forbidden_origin | CORS/WS origin |
| body_too_large / bad_json / not_found / internal | HTTP surface |
| malformed token / bad signature / undecodable payload / wrong token type / expired token | TokenError strings |

WebSocket close: 1008 origin/path/token/zone/rate; 1013 per-IP limit.

---

## 24. Seeded events (what you see on first run)

| event_id | Title | Zone | Status | Mode | Notes |
| --- | --- | --- | --- | --- | --- |
| evt_mw_basketball | Lincoln Freshman Basketball | midwest | live | single_camera | Fresh primary; score 34-29 Q3 05:12 |
| evt_mw_volleyball | Lakeside Volleyball | midwest | green | multi_camera | Cleared, not live; set score |
| evt_mw_soccer | Prairie Soccer Semifinal | midwest | live | backup_active | Fresh **backup**; 2-1 |
| evt_mw_hockey | Northside Hockey | midwest | green | single_camera | Ready to go live |
| evt_mw_wrestling | Central Wrestling (Archive) | midwest | archive | single_camera | replay_available; member archive card |
| evt_w_football | Coastal Football | west | scheduled | multi_camera | Viewer cannot watch (zone) |
| evt_w_baseball | Harbor Baseball (Replay) | west | replay | single_camera | Viewer denied by zone |
| evt_e_lacrosse | Metro Lacrosse | east | yellow | single_camera | In clearance; east |

If events already exist, seed will not duplicate them. Demo users are always upserted. Legacy `demo-admin` is deleted.

---

## 25. Security headers and CORS

Every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, Content-Security-Policy `default-src 'none'` with script/style/img/media `'self'`, `connect-src 'self'` plus the configured `ws://` or `wss://` origin, `base-uri 'none'`, `form-action 'self'`, `frame-ancestors 'none'` (so this page cannot be iframed from elsewhere; the owner pane **fetches** HTML instead of iframe).

API and media: `Cache-Control: no-store`.

CORS: exact origin match from `TZ_ALLOWED_ORIGINS`, credentials true, never `*`. OPTIONS allows GET, POST, headers Authorization, Content-Type, X-Media-Service-Key.

Production also requires token secret ≠ media key, both ≥ 32 chars, not demo values, origins set, XRPL complete, seed passwords not demo.

See `SECURITY.md` for the socket threat table and launch gates (OIDC, TLS, Postgres, durable bus, managed CDN, KMS, WORM SIEM, youth privacy, counsel-reviewed rights).

---

## 26. Configuration reference

| Variable | Default | Meaning |
| --- | --- | --- |
| TZ_ENV | development | demo/local/development allow Treasure simulation; production is strict |
| TZ_HTTP_HOST / TZ_HTTP_PORT | 127.0.0.1 / 8000 | HTTP bind |
| TZ_WS_HOST / TZ_WS_PORT | 127.0.0.1 / 8765 | Socket bind |
| TZ_ALLOWED_ORIGINS | derived from HTTP | Exact CORS and WS Origin |
| TZ_DATABASE_PATH | data/three_zone.sqlite3 | SQLite file |
| TZ_TOKEN_SECRET | demo string | HMAC for session/lease/ingest |
| TZ_MEDIA_SERVICE_KEY | demo string | Media proxy and media/end |
| TZ_SESSION_TTL | 3600 | Seconds |
| TZ_LEASE_TTL | 90 | Seconds |
| TZ_INGEST_TTL | 21600 | Seconds |
| TZ_HEARTBEAT_TIMEOUT | 12 | Seconds |
| TZ_SEED_PASSWORD_* | change-me-*-local | Demo accounts |
| XRPL_RPC_URL | empty | Production required |
| XRPL_NETWORK | empty | Production required |
| XRPL_AUDIT_ACCOUNT | empty | Production required |
| XRPL_SIGNING_SECRET | empty | Production required; never in public config |
| XRPL_KEY_ID | empty | Production required |

`run.py --http-port --ws-port --host` override binds.

Public config JSON: env, ws_url_base, session_ttl, lease_ttl, heartbeat_timeout, zones, simulation boolean, register_enabled.

---

## 27. Source files (what each file is)

**three-zone-mvp/**

- `run.py` — process supervisor
- `THREE_ZONE_MASTERY.md` — this article
- `README.md` — operator quick start
- `SECURITY.md` — threat model and launch gates
- `config.example.env` — copy-paste env
- `requirements.txt` — websockets
- `Dockerfile` — production image + ffmpeg
- `backend/config.py` — env and production refusal
- `backend/db.py` — schema
- `backend/passwords.py` — PBKDF2
- `backend/tokens.py` — HMAC tokens
- `backend/seed.py` — demo users and events
- `backend/control_plane.py` — the authority
- `backend/portal.py` — member, Treasure, schedules, XRPL publish
- `backend/http_server.py` — HTTP/CORS/CSP/cookies
- `backend/ws_server.py` — socket hub
- `backend/demo_media.py` — local MP4 seam
- `backend/mastery.py` — this article → HTML
- `backend/static/index.html` `portal.js` `styles.css` — member site
- `backend/static/ops.html` `app.js` `ops.css` — control plane
- `scripts/ingest_heartbeat.py` — encoder example
- `tests/test_control_plane.py` `tests/test_portal.py` — the contract

**repo root**

- `index.html` — Moten IP control plane
- `README.md` — Moten prototype intro
- `timezone-clock.html` — unrelated clock
- `.cursor/serve.py` — static server for Moten HTML

---

## 28. Tests that lock the contracts

36+ unit tests. The important promises:

- Live lease issues and validates for a midwest viewer
- West event is `zone_not_entitled`
- Revoke invalidates the lease; restore is version 2; old lease is `rights_version_changed`
- Illegal lifecycle skip rejected; green/live need heartbeat
- media/end needs the service key
- Ingest token cannot heartbeat a different event or source
- Tampered session/lease/wrong type rejected
- Member cannot operate; worker cannot own; owner can both
- Inventory is owner-only, includes revoked rights history, never leaks token secrets
- Member verification required; revoked verification denies play
- Schedule versions accumulate; bad CSV rejected; catalog seed on import
- Canonical audit exists **before** simulated XRPL `VALIDATED` receipt
- Public config has no XRPL signing secret
- Concurrent first catalog load does not crash
- Password login for all three roles; bad password; register is viewer; cannot register as demo-owner
- `app.js` still contains revoke and inventory (so the control plane UI cannot be deleted silently)

---

## 29. What is simulated, and what is not built yet

**Simulated in demo:** Treasure VERIFIED receipts, XRPL publications (`DEMO-` tx ids), local color-bar MP4, Moten IP browser localStorage workflows.

**Real in this MVP:** lifecycle guards, rights versions, entitlement, HMAC tokens, lease cookies, media re-validation, ingest failover, socket origin/token limits, hash-chained audit, password login, role gates, owner print, member catalog.

**Not built yet (do not pretend they are):** live XRPL submit, OIDC, TLS termination, Postgres, Redis/NATS/Kafka fan-out, managed SRT/HLS/CDN, KMS, WORM SIEM, youth privacy review, counsel-reviewed production rights desk, TZ-02 opportunity ranking, TZ-05 money settlement, full TZ-06 relationship graph, email verification, password reset, self-service staff accounts.

This is an executable pilot of the critical loop, not a claim that a laptop process is a national broadcast network.

---

## 30. How a real game moves through the machine

1. Owner or worker creates an event (or uses a seeded one). Rights v1 exists. Status `scheduled`.
2. Encoder receives an ingest token for primary (and optionally backup). Heartbeats keep last-seen fresh.
3. Worker walks gray → yellow → green. Green is blocked until heartbeat is fresh.
4. Worker (or automation) moves green → live. Families entitled in that zone see it on Live.
5. Member signs in. Treasure (demo) verifies. Cookie + Bearer issued. Watch issues a 90-second lease cookie. Video bytes are re-checked.
6. Socket streams score and feed health. Worker may update score.
7. If rights are disputed, worker revokes. Player gets `rights.revoked`. Next media request is 403. Restore creates v2. Old leases stay dead.
8. When the game ends, media service (or worker) moves live → replay. Then later archive.
9. Every step appends operational audit. Member/portal steps also append hash-chained `audit_events`.
10. Operator publishes pending hashes. Demo writes XRPL simulator rows. Production will require real XRPL credentials.

That is every engine, every connection, and the blockchain path, in the order a human actually uses them.

---

*End of Three Zone Mastery. Print from Owner → Mastery. Live numbers print from Owner → Inventory.*
