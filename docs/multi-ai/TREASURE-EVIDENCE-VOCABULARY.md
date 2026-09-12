# Treasure ↔ THREEZONE evidence vocabulary (Y1c)

**Locked by:** Andre G0-C Decision Pack (2026-09-12)  
**Scope:** Language and contracts only. Does **not** implement Treasure review seats or a THREEZONE approval ledger.

## Naming trap

A repository adapter named **Moten** (`MotenIntakeService`, `apps/control-plane/moten/`) does **not** create a Treasure institution, department, or review engine called Moten.

In Treasure Network product docs, “Moten” appears as author identity only. Treat Moten code in this repo as a **THREEZONE handoff / control-plane implementation name**, not as proof of Treasure Path A governance.

## Ownership (G0-C)

| Layer | Owner |
|-------|-------|
| Sports truth (score, clock, rights, lease, settlement) | THREEZONE |
| Evidence **proposal**, hashes, provenance, outbox, delivery receipts | THREEZONE |
| Canonical evidence **packet / revision**, review history, release | **Treasure** (Path A lane) |
| Weather / web / public / gov reference feeds | External Data Gateway → **API Admission** (Path B) |

THREEZONE must never create a competing canonical approval ledger. It may show **projections** of Treasure status only.

## Path A vs Path B

- **Path A (normal for THREEZONE evidence):** producer → Treasure THREEZONE evidence lane → Reviewer 1 → independent Reviewer 2 → Release Authority.  
  Hard inequality: `producer ≠ reviewer_1 ≠ reviewer_2 ≠ release_authority` (stable principal IDs).
- **Path B:** external sources Treasure admits via API Admission — not core THREEZONE event evidence merely because a camera/API touched it.

Reuse the **governance pattern** (dual independent review + separate release). Do **not** encode THREEZONE evidence as fake surveys or API Admission records.

## Proposal vs canonical packet

- THREEZONE owns an **Evidence Proposal** (`proposal_id`, source hashes, lineage, payload hash, delivery state).
- Treasure owns the **Canonical Evidence Packet / Revision**.
- THREEZONE may retain `canonical_packet_id`, `canonical_revision_id`, and a read-only `canonical_status` projection.

## State vocabulary

| State | Meaning |
|-------|---------|
| `submitted` | THREEZONE created proposal |
| `queued_for_delivery` | Waiting to send |
| `delivered` | Treasure endpoint received transport |
| `admitted` | Treasure accepted packet into its queue |
| `review_1_pending` | Awaiting first reviewer |
| `review_1_complete` | First reviewer completed |
| `review_2_pending` | Awaiting second independent reviewer |
| `review_2_complete` | Second reviewer completed |
| `release_pending` | Awaiting release authority |
| `released` | Authorized for that packet’s defined downstream use |
| `rejected` | Revision rejected |
| `held` | Cannot proceed |
| `corrected` | New revision required/created |
| `superseded` | Historical revision replaced |

## Killer rule

`delivered`, `received`, `ingested`, `admitted`, and transport-level acceptance can **NEVER** mean `released`.

Ban bare product language **“accepted”** for governance. Prefer:

- transport field: `intake_accepted` (payload received into Moten/control-plane intake storage only)
- UI: **“Received by Treasure”** until humans complete Path A release

Local AI lineage `approve` is **not** Treasure Reviewer 1 / Reviewer 2 / Release Authority.

## Packet family (taxonomy only — not implement-all)

Family: `THREEZONE`. Example types: `THREEZONE_MEDIA_TRANSCRIPT`, `THREEZONE_SPORTS_VISION`, `THREEZONE_DISTRIBUTION_ACTION`, `THREEZONE_MODERATION_CASE`, `THREEZONE_ARCHIVE_CANDIDATE`, `THREEZONE_EXTERNAL_CLIP_RELEASE`.
