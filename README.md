# Moten IP & Invention Control Plane

Phase 1 (Days 0–30), Phase 2 (Days 31–90), Phase 3 (Months 3–6), and Phase 4 (Months 6–12) browser prototype for the Moten master specification.

Open `index.html` in a browser to use the confidential control-plane surface:

- Command center with irreversible-risk queue and control health
- Exact-wording Research Registry with immutable question versions
- Mechanism-first Invention Ledger seeded with all six Three-Zone and six Treasure families
- Human contribution capture that keeps AI tool-only
- Disclosure firewall with fail-closed hold/file-first preflight
- Filing calendar from the verified USPTO filing date
- Counsel workbench and explicit Phase 1 / later-phase boundary
- Phase 2 evidence integrity: SHA-256 manifests and append-only event lineage
- Default-deny access policy simulation with named role boundaries
- AI gateway ingress filtering and human-approval gating
- Provisional support matrix and prior-art review record
- Rights registry with authority, scope, version, expiry, and verification
- Policy decision point with fail-closed rights lease evaluation
- Short-lived rights lease register with event, territory, destination, use, and hard expiry binding
- Live-socket admission simulation with per-message scope and close-on-failure behavior
- Source ingest qualification and rights-bound media-object metadata
- Revocation propagation and runtime audit/SIEM feed
- Rights-aware discovery graph with identity and viewing-purpose boundaries
- Privacy-bounded measurement facts and deterministic settlement recalculation
- Partner adapter allowlist and scoped handoff validation
- WORM/legal-hold export manifest simulation
- Live incident, change-control, and 12-month docket drills

This prototype uses browser local storage for demonstration state. Phase 2 hashes/events, Phase 3 policy/lease/socket workflows, and Phase 4 discovery/measurement/settlement/evidence workflows are browser demonstrations, not production WORM, KMS, identity, gateway, or SIEM services. It does not implement production authentication, encrypted storage, media delivery, partner contracts, or legal advice.

## Moten On-Chain Audit Department V1

The root server now adds a durable, server-authoritative audit plane. The
source organization retains its canonical operational record; it emits a
minimal canonical event to the **Treasure Network Verification Gateway**.
Only a `VERIFIED` and on-chain-eligible verification envelope can enter Moten
publication governance. A blockchain receipt, when one exists, is linked back
through Treasure Network to the source record.

The default is deliberately explicit: `SIMULATED TREASURE NETWORK
VERIFICATION` and `SIMULATION · NO XRPL PUBLICATION`. A simulator receipt has
no XRPL transaction hash and must not be treated as ledger evidence.

```text
source canonical event → Treasure verification → Moten publication policy → XRPL witness
```

Run the local service with:

```bash
python3 .cursor/serve.py
```

Configuration is backend-only; copy `.env.example` values into the execution
environment rather than a browser. `MOTEN_XRPL_SECRET` is never returned,
logged, or stored in the audit database. Mainnet is intentionally disabled.
Real testnet publication additionally requires a real XRPL client, an
authorized human signing profile, and separately supplied backend credentials.

The durable tables include canonical audit events and versions/lineage,
Treasure verification records/history, publication requests/attempts/receipts,
signing-profile audit, and reconciliation/health records. Key APIs are
`POST /api/audit/events`, `POST /api/treasure/verifications/{event_id}`,
`POST /api/onchain/publications`, `POST /api/onchain/publications/{id}/approve`,
`GET /api/onchain/receipts/{event_id}`, `POST /api/onchain/reconcile`, and
`GET /api/onchain/health`.