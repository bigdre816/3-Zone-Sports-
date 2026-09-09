# Moten Control Plane — Phase 1 (Days 0–30) Design Plan

**Status:** Draft for review (the "read its plan" gate). No application code is built yet.
**Scope authority:** Master Specification V1.0, §20 Implementation Roadmap, "Days 0–30" row.
**Governing invariants:** `AGENTS.md` §2 (constitution), §4 (planes), §5 (IDs/versioning), §6 (AI limits), §7 (build order).

---

## 1. Objective and exit evidence

Phase 1 builds the **irreversible-risk controls first** — the records, versioning, disclosure gate, and calendar that must exist *before* any operating-company runtime. The spec's exit evidence for Days 0–30 is the acceptance bar for this phase:

- **One real candidate reconstructed end-to-end**: from a research question version → observation → invention candidate with a mechanism and human-contribution record → disclosure decision → calendar → hash-linked export.
- **No public-release bypass**: every disclosure attempt passes through preflight; unfiled/secret-linked artifacts are held or blocked.
- **Deadlines visible**: a filing calendar renders the 6/9/10/11-month escalation and the 12-month hard deadline from a verified filing date.

MVP acceptance criteria carried from spec §20 that Phase 1 owns:

- A user can create a question, version it, attach an observation, create an invention candidate, record human contribution, and produce a hash-linked export.
- A public deck / partner artifact is blocked or approved based on linked unfiled inventions and secret tags, with a recorded decision and artifact hash.
- A filed candidate shows receipt, inventor list, supported versions, 6/9/10/11 alerts, and the 12-month decision.

## 2. In scope vs. explicitly deferred

**In scope (Phase 1):**
- Canonical IDs + immutable versioning substrate (all object types).
- Signal plane: Longitudinal Research Registry.
- Invention plane: Insight-to-Invention Ledger (mechanism-first) + candidate lifecycle state machine + human-contribution / AI-assistance records.
- Decision plane: Disclosure preflight firewall (intake → classification → link analysis → risk → approval → release → aftercare) + patent/trade-secret posture capture.
- Filing calendar with escalation from a verified filing date.
- Counsel/governance workbench (read + triage surfaces).
- Restricted storage boundary for Vault-class material (labels + access separation; deep crypto is Phase 2).
- Seed data: six Three-Zone candidates (TZ-01…TZ-06) and six Treasure candidates (TR-01…TR-06) as records.

**Deferred (build interfaces only, do not implement):**
- Phase 2: content-hash manifests at scale, append-only signed event chain, formal access-policy engine, AI gateway enforcement, support-matrix builder, first rights object.
- Phase 3: Policy Decision Point, rights leases, WebSocket/media gateways, ingest qualification, revocation propagation, SIEM.
- Phase 4: discovery graph, measurement facts, settlement ledger, partner adapters, WORM object-lock, dashboards, operational drills.

For each deferred capability we define a **stub interface** (a service boundary / table column / API route reserved) so later phases slot in without reshaping Phase 1 data. See §11.

## 3. Recommended technology shape (decision point — please confirm)

The spec specifies *shapes*, not products (§20 "Recommended minimum stack shape"). Recommended defaults, chosen for immutable-version modeling, typed contracts, and auditability:

| Concern | Recommendation | Why | Alternative |
| --- | --- | --- | --- |
| System of record | **PostgreSQL** | Mature row-level security, transactional audit, JSONB for envelopes, `tstzrange` for bitemporal validity | Any relational DB with RLS |
| Backend | **TypeScript + Node (Fastify)** or **Python (FastAPI)** | Typed API contracts; strong schema-validation ecosystems | Either; pick one and standardize |
| API contract | **OpenAPI 3.1**, schema-first | Contracts double as spec-traceability artifacts | gRPC (heavier for Phase 1) |
| Auth (humans) | **OIDC** provider + phishing-resistant MFA | Spec §20 identity target | Managed IdP |
| Web UI | **React + TypeScript** (SSR optional) | Component-driven workbench surfaces | SvelteKit |
| Evidence hashing | **SHA-256** in app layer now; WORM object store in Phase 4 | Spec §16 | — |
| Migrations | Versioned, forward-only, append-style | Mirrors "no destructive edits" | — |

**Default assumption unless you say otherwise:** PostgreSQL + FastAPI (Python) + React/TypeScript, OpenAPI-first, single deployable modular monolith with plane-separated modules and schemas (not microservices yet). This keeps Phase 1 small while preserving the six-plane boundary logically.

## 4. Immutable-version model (foundation for everything)

Every object type shares a common versioning substrate. Two-table pattern per object family:

- **Identity table** (`*_object`): the permanent ID (`RQ-YYYY-NNNNNN`), object type, created_at, current_version pointer, lifecycle state. One row per logical object.
- **Version table** (`*_version`): immutable rows. Columns: `object_id`, `revision` (monotonic int), `semver_label` (`v1.0`…), `valid_from`, `valid_to`, `recorded_at`, `payload` (typed columns + JSONB), `payload_sha256`, `status` (`active | superseded | corrected | withdrawn | rejected`), `supersedes_revision`, `change_reason`, `authored_by`, `attestation`.

Rules enforced at the DB + service layer:

1. **No `UPDATE`/`DELETE` on version rows.** New facts are new rows. A DB trigger rejects mutation of any column except a controlled `status` transition to a superseded-family value with a `change_reason`.
2. **Bitemporal**: `valid_from`/`valid_to` = intended applicability; `recorded_at` = when Moten learned it. Queries are "as-of" both axes.
3. **Compensating corrections**: a correction is a new version (`status=corrected` on the old, new row references `supersedes_revision`). Prior result is preserved and remains queryable.
4. **Split/merge**: explicit `object_relation` rows (`parent_id`, `child_id`, `relation=split|merge`, `decision_id`, reason). Parent retained.
5. **Every ID generated centrally** by an ID service that guarantees prefix + zero-padded sequence per year.

Canonical event log (`event`) uses the envelope from `AGENTS.md` §5, with `previous_event_hash` present but the full signed chain is a Phase 2 hardening (Phase 1 records the fields; Phase 2 enforces the cryptographic chain + WORM).

## 5. Database schema (Phase 1 tables)

Logical grouping by plane; each in its own Postgres schema (`signal`, `invention`, `decision`, `evidence`, `directory`) to make the boundary real.

**Directory / shared**
- `directory.person(person_id PK, display_name, role_default, is_natural_person BOOL, status)` — natural-person registry; AI tools are **not** persons.
- `directory.id_sequence(prefix, year, last_value)` — central ID allocation.
- `directory.project(project_id PK, name)` — Three-Zone / Treasure / Passport / future.

**Evidence plane**
- `evidence.artifact(evd_id PK, sha256, mime, byte_size, storage_ref, data_class, created_at)` — content-addressed artifacts.
- `evidence.event(event_id PK, event_type, object_id, object_version, actor_person_id, actor_role, recorded_at, clock_source, payload_sha256, previous_event_hash, attestation, legal_effect, links JSONB)`.
- `evidence.legal_hold(hold_id PK, matter, scope JSONB, custodian, opened_at, released_at, release_authority)`.

**Signal plane — Research Registry** (identity + version pattern)
- `signal.research_question(rq_id PK, owner_person_id, project_id, parent_instrument_id, language, current_revision, longitudinal_intent ENUM[stable|controlled|exploratory])`.
- `signal.research_question_version(rq_id FK, revision, semver_label, exact_wording TEXT, response_contract JSONB, first_use_date, valid_from, valid_to, recorded_at, sampling JSONB, collection JSONB, change_reason, comparability_assessment TEXT, status, payload_sha256)`.
- `signal.observation(obs_id PK, rq_id, rq_revision, project_id, recorded_at, source_ref, data_class, payload JSONB, evidence_links JSONB)` — observations reference the **exact** question version.

**Invention plane — Insight-to-Invention Ledger**
- `invention.invention(inv_id PK, project_id, root_inv_id, current_revision, lifecycle_state ENUM, ip_posture ENUM[patent|trade_secret|hybrid|copyright|hold])`.
- `invention.invention_version(inv_id FK, revision, semver_label, problem TEXT, mechanism JSONB{inputs,transformation,outputs}, technical_context JSONB, alternatives JSONB[≥3], differentiators TEXT, failure_behavior JSONB, security_privacy_boundary JSONB, test_evidence JSONB, recorded_at, valid_from, valid_to, authored_by, status, payload_sha256)`.
- `invention.embodiment(emb_id PK, inv_id, label, revision, package JSONB, recorded_at, status)`.
- `invention.contribution(contribution_id PK, inv_id, inv_revision, person_id, class ENUM[problem|constraint|mechanism|selection|implementation|verification], statement, evidence_ref, attested BOOL, attested_at)`.
- `invention.ai_interaction(ai_record_id PK, inv_id, human_operator_person_id, tool, model_identifier, purpose, prompt_hash, output_hash, sensitive_data_filter, human_action, human_conception_attestation BOOL, inventor_status_of_ai CONST 'tool_only', retention)`.

**Decision plane — Disclosure firewall + IP posture + filing**
- `decision.disclosure(disc_id PK, artifact_sha256, channel, audience JSONB, proposed_at, classification ENUM, linked_unfiled_inventions JSONB, linked_trade_secrets JSONB, nda JSONB, decision ENUM[green|amber|red|black|hold_file_first], approvers JSONB, conditions JSONB, released_artifact_sha256, released_at)`.
- `decision.counsel_decision(dec_id PK, subject_object_id, kind, decided_by, decided_at, outcome, reason, source_versions JSONB)`.
- `decision.filing(app_id PK, inv_id, uspto_receipt_ref, verified_filing_date, named_inventors JSONB, supported_versions JSONB, filing_pdf_evd_id, recorded_at)`.
- `decision.calendar_entry(cal_id PK, app_id, clock_point ENUM[T0|T7d|T30d|T60_90|T6m|T9m|T10m|T11m|T12m|post], due_date, counsel_confirmed_due_date, owner, backup_owner, escalation_owner, ack_deadline, ack_record JSONB, status ENUM[open|acknowledged|escalated|closed])`.
- `decision.trade_secret(ts_id PK, owner_person_id, sensitivity, purpose, version, handling_label, review_date, access_policy JSONB)` — Phase 1 captures labels/access intent; enforcement deepens in Phase 2.

All version tables carry the DB trigger from §4. All schemas have row-level security posture reserved (enforced fully in Phase 2 access-policy work).

## 6. Authorization model (Phase 1)

Phase 1 uses **role-based, default-deny** authorization aligned to the spec's accountable owners; the full policy-engine/PDP is Phase 2–3.

- **Identity**: OIDC humans only. Every actor resolves to a `directory.person` with `is_natural_person=true`. Service/automation principals are distinct and can never be recorded as an inventor/contributor.
- **Roles** (least privilege): `research_steward`, `product_owner`, `inventor`, `technical_lead`, `ip_steward`, `counsel`, `security_records_steward`, `founder`, plus read-only `viewer`.
- **Plane ownership** maps to `AGENTS.md` §4. Write access to a plane is limited to that plane's accountable roles; cross-plane links are allowed but do not grant cross-plane write.
- **Two-person control** for irreversible actions (`AGENTS.md` §6): moving an invention to `Filed`/`Publicly Disclosed`/`Trade Secret Protected`, naming inventors, patent/TS classification, and any disclosure `green` release require a second distinct human approver recorded on the event. The service refuses if creator == approver.
- **Vault-class data** (`P4`, unfiled invention detail, TS values) is access-separated by schema + role now; export is blocked by default and only Phase 2 adds cryptographic enforcement.

## 7. Workflows / state machines

**Invention candidate lifecycle** (spec §05):

```
Observation → Hypothesis → Mechanism → Invention Candidate → Prior-Art Review
  → Provisional Ready → Filed → 12-Month Decision → Continuation Family
  → { Granted | Abandoned | Trade Secret }
```

Guards (fail-closed): advancing past `Mechanism` requires inputs/transformation/outputs present; past `Invention Candidate` requires ≥1 embodiment + a stated technical effect + assigned IP posture; entering `Provisional Ready` requires a support-matrix stub, named inventors, alternatives, best-mode note, and disclosure history; entering `Filed` requires a verified USPTO receipt (two-person + counsel). Every transition emits an `evidence.event`.

**Disclosure preflight** (spec §08): `Intake → Classification → Link analysis → Risk result → Approval → Release → Aftercare`. Risk statuses `green | amber | red | black`; default is **hold-file-first** when an unfiled patent candidate is present and the disclosure is not a controlled legal/diligence purpose. `black` attempts create a security-incident record.

**Filing calendar** (spec §10): entries are generated from `verified_filing_date` and **cannot** be reset by editing a draft. Escalation ladder T+6/9/10/11 months; T+11 forces all unresolved to red (no silent snooze); T+12 is a hard deadline requiring an evidenced disposition. Weekend/holiday due dates store both the raw calendar date and the counsel-confirmed date.

## 8. API plan (Phase 1 subset of spec §13 surface)

OpenAPI-first. Phase 1 routes (later-phase routes are documented as reserved, returning `501 Not Implemented`):

- `POST /v1/research/questions` — create immutable question version; link instrument/sample.
- `POST /v1/research/questions/{id}/versions` — new version with diff + comparability assessment.
- `POST /v1/research/observations` — record observation bound to an exact question version.
- `POST /v1/inventions` — create INV candidate with human owner + initial evidence links.
- `POST /v1/inventions/{id}/versions` — commit a human-attested mechanism/embodiment revision.
- `POST /v1/inventions/{id}/contributions` — record human contribution / attestation.
- `POST /v1/inventions/{id}/ai-interactions` — record AI-assistance (tool_only).
- `POST /v1/inventions/{id}/transition` — guarded lifecycle transition (two-person where required).
- `POST /v1/disclosures/preflight` — classify artifact, intersect linked IP/secrets, return allow/hold.
- `POST /v1/disclosures/{id}/approve` / `.../release` — recorded approval + release hash capture.
- `POST /v1/filings` — store verified receipt; generate calendar entries.
- `GET /v1/calendar` — render escalation ladder and due dates.
- `POST /v1/exports/invention/{id}` — produce a hash-linked evidence export package (spec §16).
- **Reserved (501):** `/v1/rights/**`, `/v1/live/**`, `/v1/settlements/**`, `/v1/discovery` — Phase 3–4.

Every response that shows a date includes its legal label (`internal_provenance | public_disclosure | uspto_filing`).

## 9. UI surfaces (Phase 1)

Counsel + governance workbench, minimal but real:

- **Candidate dashboard** — list of inventions with lifecycle state, IP posture, earliest supported filing date, next irreversible deadline, disclosure status (spec's "date is a control" banner on every date).
- **Invention detail** — mechanism (inputs→transformation→outputs), alternatives, failure behavior, contribution matrix, AI-interaction log, evidence links, transition controls with two-person prompt.
- **Research Registry** — question versions with exact wording, response contract, longitudinal intent, and a version diff/comparability view.
- **Disclosure preflight** — submit artifact → see classification, linked IP/secret intersections, risk color, approval workflow.
- **Filing calendar** — timeline of 6/9/10/11-month alerts + 12-month hard deadline with acknowledgment state.
- **Evidence export** — build + download a hash-manifest package for one candidate.

## 10. Testing strategy

Because Phase 1 *is* the irreversible-risk control layer, tests target the invariants, not just happy paths.

- **Unit** — ID allocation (prefix/format/sequence), version status transitions, calendar date math (including weekend/holiday → counsel-confirmed).
- **Invariant/property tests** — (a) version rows are immutable: any `UPDATE`/`DELETE` is rejected by trigger; (b) a correction preserves the prior version; (c) no state transition bypasses its guard; (d) disclosure defaults to hold-file-first when unfiled IP is linked; (e) creator == approver is rejected for two-person actions; (f) AI can never be recorded as inventor/contributor.
- **Integration** — end-to-end reconstruction of one candidate (the phase exit evidence) as an automated test.
- **Contract** — OpenAPI schema validation for every route; reserved routes return 501.
- **Security smoke** — default-deny checks per role/plane; Vault-class export blocked.
- **Date-label test** — every date-bearing API field and UI element carries a legal label.

CI gate: invariant + integration suites must pass before merge (mirrors `AGENTS.md` §8 definition of done).

## 11. Deferred-interface stubs (so Phase 2–4 slot in cleanly)

- **Signed event chain / WORM**: `evidence.event` already carries `previous_event_hash`/`attestation`; Phase 2 turns on hashing/signing + object-lock storage.
- **Rights object**: reserve `RIGHTS` prefix + `runtime` schema (not created in Phase 1); `/v1/rights/**` returns 501.
- **Policy Decision Point / leases / sockets**: reserved routes + a `policy_decision` event_type placeholder; no runtime enforcement in Phase 1.
- **Measurement/settlement**: reserved `settlement` schema + 501 routes.
- **AI gateway enforcement**: Phase 1 records AI interactions; Phase 2 adds ingress filtering + action allowlist.

## 12. Deployment plan (Phase 1)

- **Local dev**: containerized Postgres + the backend + the web UI via Docker Compose; seed script loads the 6 TZ + 6 TR candidate records and one fully reconstructed sample candidate for the exit-evidence test.
- **Migrations**: forward-only, versioned; the immutability trigger ships as an early migration.
- **Environments**: single modular-monolith deployable; secrets via environment/secret store (never in repo, per `AGENTS.md` §6/§9). This repo's `.cursor/environment.json` will be updated to install deps, run migrations + seed, and serve the app for Cloud Agents.
- **Observability**: structured audit logging that never logs secrets or Vault-class payloads (spec §14 SEC-SOCK-16 principle applied early).
- **CI/CD**: lint + type-check + invariant/integration tests as the merge gate.

## 13. Requirements traceability — satisfied vs. deferred

| Spec section | Requirement | Phase 1 |
| --- | --- | --- |
| §00–§02 | Four linked histories; control-plane constitution | **Enforced** in schema/services/UI |
| §03 | Canonical IDs + immutable bitemporal versioning + event envelope | **Satisfied** (signed chain hardening → P2) |
| §04 | Longitudinal Research Registry | **Satisfied** |
| §05 | Insight-to-Invention Ledger + lifecycle + mechanism-first | **Satisfied** |
| §06 | Human contribution + AI-assistance records; AI cannot be inventor | **Satisfied** |
| §07 | Technical embodiment package + support matrix | **Partial** (embodiment captured; support-matrix builder → P2) |
| §08 | Disclosure firewall | **Satisfied** |
| §09 | Patent/trade-secret split + TS control set | **Partial** (posture + labels; deep TS controls → P2) |
| §10 | Filing calendar 6/9/10/11 + 12-month hard deadline | **Satisfied** |
| §11–§12 | TZ-01…06 / TR-01…06 candidate families | **Seeded as records** (mechanisms captured over time) |
| §13 | Runtime reference architecture, rights object, API surface | **Deferred → P3** (routes reserved, 501) |
| §14 | Live-socket security profile | **Deferred → P3** |
| §15 | Privacy/youth/AI runtime controls | **Deferred → P3** (data-class tags captured now) |
| §16 | Evidence integrity + export package | **Partial** (SHA-256 + export now; WORM/signed chain → P4) |
| §17 | Measurement & settlement integrity | **Deferred → P4** |
| §18 | Master control matrix | **Partial** (IP/date/disclosure/calendar controls now; SEC-SOCK → P3) |
| §19 | Operating playbooks A–D | **A/B supported** by Phase 1 surfaces; C/D reference later phases |
| §20 | Roadmap / MVP acceptance | Phase 1 owns Days 0–30 exit evidence |
| §21 | Operating forms (capture, attestation, checklists) | **Satisfied** as UI forms |
| §22 | V2.1 mapping | Recorded as candidate links |

## 14. Open decisions for you (blocking a clean build start)

1. **Tech stack** — confirm the §3 default (PostgreSQL + FastAPI + React/TS, modular monolith) or pick another shape.
2. **Repo layout** — does the existing investment-tracker `System` app stay in this repo (as an early Passport/Treasure prototype) or move out? Phase 1 code would live under e.g. `apps/control-plane/`.
3. **Identity provider** — which OIDC provider for the dev/counsel workbench.
4. **Counsel involvement** — the constitution routes irreversible actions through counsel; for the build, confirm we model counsel as a role with test users (no real legal workflow wired yet).

Once these are confirmed, Phase 1 implementation can begin against this plan without reshaping the data model.
