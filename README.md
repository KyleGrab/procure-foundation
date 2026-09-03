# ProcureIQ

Procurement intelligence and margin-protection platform for South African food distributors,
retailers, restaurant groups, and related businesses. Internal codename; branding is
config-driven (`app.branding.*`), not hardcoded.

## Status

Phase 1 (foundation), Phase 2 (supplier price review), Phase 3 (contract lifecycle), Phase 4a/4b/4c
(rebate leakage — manual entry, minimal transaction ledger, and the full purchase order/invoice/goods
receipt ledger), and Phase 5 (opportunity engine, spend analytics, Safe AI Copilot) are built. 152
`unittest` tests genuinely
executed against real business logic (matching, calculations, ingestion, escalation, rebate math) — not
just written, and running them caught real bugs along the way (see the phase plan docs below for each
one). DB models, migrations, service layer, and FastAPI routes are syntax-checked but not run: this was
built in a sandbox with no network access, so there's no Postgres/FastAPI/SQLAlchemy actually running
here. General master-data/product-catalog CRUD (a global `products` table, distinct from
Phase 4c's supplier-linked purchase records) remains
deliberately unbuilt — see `docs/implementation-plan.md` for the phase-by-phase gate status.

**Before trusting it, run it**: see "Local development" below.

**Before trusting any of this in an environment handling real tenant data, read
`docs/decisions/ADR-011-least-privilege-role-force-rls.md` and run
`docs/deployment-rls-checklist.md`'s checks.** RLS did not actually protect anything from Phase 1
through Phase 3 due to a table-ownership gap only found while writing the RLS integration suite — fixed
in migration 0004, but worth verifying directly rather than taking on faith in any new environment.

## Read first

- `UNIVERSAL_ENGINEERING_SPEC.md` — the root engineering-standards reference for this project
  (verification discipline, architectural guardrails, catalogued failure patterns). Read this
  first; every other doc in this list is this project's specific application of it.
- `docs/architecture.md` — system shape and the original architectural deviations (tenant isolation,
  primary keys, job queue sequencing, settings storage, financial-fact mutability, AI-extraction
  gating, multi-org session design).
- `docs/data-model.md` — ERD and table definitions, reflecting what's actually built (migrations
  0001–0008), not just the original plan.
- `docs/api.md` — endpoint map, phase by phase, marking BUILT vs. reserved.
- `docs/security.md` — auth, RBAC, tenant isolation, the consultant multi-org threat model, and the
  ADR-011 RLS finding.
- `docs/analytics-methodology.md` — every financial formula, with rounding rules, as the single
  source of truth calculation code must match.
- `docs/implementation-plan.md` — phase gates and acceptance criteria, kept current with actual status.
- `docs/deployment-rls-checklist.md` — run this (or the automated suite it points to) before any
  environment holds more than one organisation's data.
- `docs/phase2-price-review-plan.md`, `docs/phase3-contract-lifecycle-plan.md`,
  `docs/phase3-frontend-specs.md`, `docs/phase4-rebate-leakage-plan.md` — the per-phase plans, scope
  reconciliations, and what's genuinely verified vs. syntax-checked-only for each.
- `docs/decisions/` — 13 ADRs, one per non-obvious architectural call, each with the reasoning and
  what it costs.

## Local development

Requires Docker, Python 3.12+, Node 22+. This has **not been run** in the environment that wrote
it (no network access there) — run it somewhere with network access before relying on it:

```bash
cp .env.example .env
# edit .env: set a real SECRET_KEY (openssl rand -hex 32) and LLM_API_KEY if using the AI copilot later

docker compose up -d postgres redis minio
cd backend
pip install -e ".[dev]"
alembic upgrade head
# ^ this now does more than create tables (ADR-011): it also creates the procureiq_app role the
# running application actually connects as. The API will fail every DB call with an
# authentication error until this has run - there is no more "run the app first, migrate later."
pytest -v          # includes the tenant-isolation test - this is the one that actually matters
uvicorn app.main:app --reload

# separate terminal
cd frontend
npm install
npm run dev
```

Then: register at `http://localhost:3000/register`, confirm you land on `/dashboard`, and check
`backend/tests/test_tenant_isolation.py` passes — that test is the Phase 1 gate criterion from
`docs/implementation-plan.md`.

For the RLS-specific verification (the most important thing to check before this ever holds real
data — see "Status" above): `pytest backend/tests/test_rls_integration.py -v`. This spins up its
own ephemeral Postgres via `testcontainers` (needs Docker running), separate from the
`docker compose` one above — it does not need `alembic upgrade head` run first, it runs the full
migration chain itself against a throwaway database.

## Repository layout

```
backend/    FastAPI app, SQLAlchemy models, Alembic migrations, services, tests
frontend/   Next.js app (App Router, TypeScript, Tailwind)
docs/       Architecture, data model, API map, security model, analytics methodology, ADRs
data/       Synthetic seed data (Phase 2+)
scripts/    Dev/ops scripts
```
