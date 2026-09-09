# Moten Control Plane — Phase 1

Phase 1 (Days 0–30) implementation of the Moten IP & Invention Control Plane.
Governing spec: `docs/Moten_IP_Invention_Control_Plane_Master_Specification_v1_0.pdf`.
Design: `docs/phase-1-plan.md`. Operating rules: `AGENTS.md`.

## What Phase 1 implements

- Canonical IDs + an immutable, bitemporal version substrate (DB triggers reject
  deletes/frozen-column updates; only `status`/`change_reason` may transition).
- **Signal plane** — Longitudinal Research Registry (question versions never
  edited in place; observations bound to an exact question version).
- **Invention plane** — mechanism-first ledger, human-contribution and
  AI-interaction records (AI is `tool_only`, never an inventor), lifecycle state
  machine with fail-closed guards, two-person control on irreversible actions.
- **Decision plane** — disclosure firewall (default hold-file-first; black →
  security incident), verified filing, and a 6/9/10/11-month + 12-month-hard
  calendar generated from the verified filing date.
- **Evidence plane** — append-only hash-chained event log and a counsel-ready,
  hash-linked export package.
- Reserved later-phase routes fail closed with `501` (spec §13–§17).

## Run

```bash
pip install --break-system-packages -r requirements.txt   # or use a venv
python3 manage.py serve        # seeds the dev store, serves http://localhost:8100/
python3 manage.py reset        # wipe + reseed the dev store
python3 -m pytest -q           # invariant + API + integration tests
```

## Persistence

Phase 1 dev store is SQLite via a DB-agnostic SQLAlchemy layer. PostgreSQL (the
spec's production target) is a connection-string swap:

```bash
MOTEN_DB_URL=postgresql+psycopg://user:pass@host/moten python3 manage.py serve
```

## Decisions / deviations (Phase 1)

- SQLite dev store instead of a running Postgres cluster (see above).
- Server-rendered UI instead of a separate React app; the JSON API is
  OpenAPI-first (`/docs`) so a React front-end can be added later.
- Dev auth selects the acting person via the `X-Moten-Actor` header / `actor`
  cookie. Real OIDC + phishing-resistant MFA is a later-phase target.
