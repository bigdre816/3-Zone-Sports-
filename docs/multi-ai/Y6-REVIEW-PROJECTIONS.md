# Y6 — Independent review + immutable revisions (projections only)

**Scope:** Read-only **projections** of Treasure Path A review/revision status
onto THREEZONE. Seats stay in Treasure.

**Depends on:** Y5 Treasure delivery + reconciliation, Y1c vocabulary, G0-C.

**Authorized by:** Andre (2026-09-12) — projections only in THREEZONE.

## Intent (Andre / G0-C)

Project Treasure Path A status so THREEZONE can display evidence progress
without owning review seats or a second approval ledger.

| Layer | Owner |
|-------|-------|
| Evidence proposal, hashes, provenance, outbox, delivery receipts | **THREEZONE** |
| Canonical packet / revision, dual review, release authority | **Treasure** |
| Read-only `canonical_*` + append-only revision projections | **THREEZONE** (mirror) |

## Hard bans (G0-C)

- **NO** R1 / R2 / Release seat assignment, approval actions, or second approval DB in THREEZONE
- **NO** competing canonical review/release ledger
- THREEZONE **may**: apply Treasure status receipts → update `canonical_*` projections; append-only immutable revision projection records
- Bare product language **`accepted` is banned** as governance
- `intake_accepted` (Y5 transport) **≠** `released`
- Local `treasure_release` authority flag stays **`false`**; projecting Treasure `released` uses `canonical_status=released` as **projection only**

## Projection vocabulary (this slice)

| `canonical_status` | Meaning (projection) |
|--------------------|----------------------|
| `admitted` | Treasure accepted packet into its queue |
| `in_review` | Path A review in progress (aggregate projection) |
| `changes_requested` | Reviewers requested changes / new revision |
| `released` | Treasure released — **projection only** in THREEZONE |
| `rejected` | Revision rejected |
| `corrected` | Corrected revision recorded |
| `superseded` | Historical revision replaced |

Transport-only statuses (`intake_accepted`, `delivered`, bare `accepted`, …) are
**rejected** as `canonical_status` on receipt ingest.

## Schema

Append-only table `treasure_revision_projections` (AI proposals SQLite; same
file family as Y4/Y5 outbox — not ControlPlane sports truth):

| Column | Notes |
|--------|-------|
| `projection_id` | `trp_…` primary key |
| `proposal_id` | local Y4 proposal |
| `canonical_packet_id` | Treasure projection |
| `canonical_revision_id` | Treasure projection |
| `canonical_status` | vocabulary above |
| `receipt_hash` | sha256 of cleaned receipt payload |
| `payload_json` | receipt (seat fields scrubbed) |
| `created_at` | unix seconds |

**INSERT only.** Mutate / delete always rejected (`projection_immutable`).

## Service

`TreasureProjectionService.apply_treasure_receipt(proposal_id, receipt)`:

1. Validate receipt shape / vocabulary
2. Append revision projection row
3. Mirror `canonical_*` onto latest delivery outbox row when present
4. Never set local `treasure_release=true`

## Operator API

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/api/ai-proposals/{aip_…}/treasure-projections` | Latest + revision list |
| `GET` | `/api/ai-proposals/{aip_…}/revisions` | Alias of projections list |
| `POST` | `/api/ai-proposals/{aip_…}/treasure-receipt` | **Receipt ingest** (mock/webhook) — **not** a seat / approve action |
| `GET` | `/api/ai-proposals/{aip_…}/reconcile` | Y5 reconcile also surfaces `latest_revision_projection` |

There is **no** `/approve`, `/assign-reviewer`, or R1/R2/Release endpoint in THREEZONE.

## Y5 reconcile wiring

`TreasureDeliveryService.reconcile` prefers the latest Y6 revision projection for
`canonical_packet_id` / `canonical_revision_id` / `canonical_status` when present,
and includes `latest_revision_projection`.

## Out of scope

- Y7 member panel
- Full Treasure Path A 4-seat product UI inside THREEZONE
- Prod AI flip; Restream / `LIVE_PUBLIC`; rights / score / settlement / XRPL mutation

## Implementation map

- `threezone_ai/proposals/projections.py` — store, validate, apply, list
- `threezone_ai/proposals/delivery.py` — reconcile surfaces latest projection
- `backend/ai_gateway_routes.py` — GET projections / POST treasure-receipt
- `docs/multi-ai/Y6-REVIEW-PROJECTIONS.md` — this file
