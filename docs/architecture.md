# ProcureIQ — Architecture Overview

Internal codename `ProcureIQ`. All branding is a config value (`app.branding.*`), never hardcoded into logic.

## 1. Shape of the system

Modular monolith, not microservices. One deployable backend (FastAPI), one deployable frontend (Next.js),
one Postgres, one Redis, one worker pool. Module boundaries inside the monolith (`ingestion`, `matching`,
`analytics`, `ai`, `reporting`) are drawn as if they might become services later, but nothing is split out
until there's a measured reason to.

```
                    ┌─────────────────────────┐
                    │   Next.js frontend       │
                    │  (dashboards, imports,   │
                    │   price review, copilot) │
                    └────────────┬─────────────┘
                                 │ HTTPS / JSON (REST, versioned)
                    ┌────────────▼─────────────┐
                    │   FastAPI backend         │
                    │  api/ → services/ → db/   │
                    │  (permission checks live  │
                    │   in services, not routes)│
                    └───┬───────────────┬───────┘
                        │               │
              ┌─────────▼───┐   ┌───────▼────────┐
              │  PostgreSQL  │   │     Redis       │
              │ (+ pgvector) │   │ (queue, cache,  │
              │  RLS enabled │   │  rate limiting) │
              └──────────────┘   └───────┬─────────┘
                                          │
                                 ┌────────▼─────────┐
                                 │  Background worker │
                                 │  (imports, matching,│
                                 │   AI extraction,    │
                                 │   report generation) │
                                 └────────┬─────────┘
                                          │
                                 ┌────────▼─────────┐
                                 │ S3-compatible      │
                                 │ object storage      │
                                 │ (uploads, reports)  │
                                 └────────────────────┘
                                          │
                                 ┌────────▼─────────┐
                                 │ LLMProvider         │
                                 │ abstraction          │
                                 │ (Anthropic default)  │
                                 └────────────────────┘
```

Data flow discipline (Section 37 of the spec, kept as a hard rule): the LLM never computes an authoritative
financial number. Every number that appears on a dashboard, report, or opportunity record is produced by a
Python/SQL function in `app/analytics/`, versioned, and stored with its inputs. The LLM's job is
classification, extraction, and turning a structured result into prose. If a code path exists where an LLM
response is parsed for a currency figure and written to a financial table without a deterministic
calculation behind it, that is a bug, not a feature.

## 2. Architectural decisions I'm changing from the spec, and why

The spec is very good as a first draft. A few defaults in it would cause real problems at the scale it
describes (hundreds of tenants, millions of rows, audit-grade financial output). I'm flagging these rather
than silently building the safer version, because you said you want pushback, not agreement.

### 2.1 Tenant isolation cannot be app-layer-only (Section 7)

The spec says "all queries must enforce tenant filtering" and "add tests attempting cross-tenant access."
Tests catch regressions you write tests for. They don't catch the query a tired engineer writes eighteen
months from now that forgets the `WHERE organisation_id = :org_id` clause. For a product whose entire value
proposition is *other people's confidential supplier pricing*, a single missed filter is a breach, not a bug
ticket.

**Decision:** Postgres Row-Level Security (RLS) is a mandatory second layer, not a nice-to-have. Every
tenant-scoped table gets an RLS policy keyed on a session variable (`SET app.current_org_id`) set once per
request in a DB session dependency. App-layer filtering stays (for query planning and clarity), but RLS is
what actually prevents leakage when app-layer filtering fails. This is documented in `ADR-003`.

### 2.2 UUIDv4 primary keys everywhere will hurt at the row counts the spec targets (Section 9, 60)

Random UUIDv4 as a clustered/primary index key on a table taking millions of inserts (`purchase_invoice_lines`,
`sales_facts`) causes index bloat and poor write locality — every insert lands in a random b-tree leaf. The
spec's own performance section (60) asks for "millions of invoice/purchase rows" and "batch inserts," which is
in tension with UUIDv4 PKs.

**Decision:** internal PKs are `BIGINT GENERATED ALWAYS AS IDENTITY` (or `BIGSERIAL`). A separate `public_id
UUID` (UUIDv7 — time-ordered, so still decently index-friendly, unlike v4) is what's ever exposed over the
API. Internal integer PKs never leave the backend. Documented in `ADR-005`.

### 2.3 Celery+Redis as the default is more ops surface than Phase 1–4 needs (Section 5)

Celery is the right long-term choice once you have varied task types, retries, scheduling, and multiple
queues. For the actual Phase 1–4 workload (import processing, product matching, report generation) it's
mostly "run this job, tell me when it's done." Standing up Celery well (worker pools, task routing,
monitoring, dead-letter handling) is a real chunk of engineering time that doesn't move the MVP forward.

**Decision:** kept Celery in the architecture (per your spec's explicit instruction) but sequenced it so
Phase 1–3 uses FastAPI `BackgroundTasks` + a Redis-backed job-status table for anything synchronous enough to
not need it, and Celery is introduced in Phase 3 when the import engine actually needs retries/concurrency
control. This avoids building queue infrastructure before there's a queue-shaped problem. Documented in
`ADR-002`.

### 2.4 A single `organisation.settings` JSON blob undermines the audit requirement (Section 111, 54)

The spec wants configurable thresholds (price-risk bands, savings-validation rules, slow-stock thresholds,
margin targets, supplier scoring weights) *and* wants critical actions audited (Section 54). A single opaque
JSON column that gets overwritten on every settings change gives you no "who changed the margin target from
30% to 28%, and when" — which is exactly the kind of thing Finance will ask about during a quarterly
reconciliation.

**Decision:** `organisation_settings` is a structured, versioned table (one row per setting key, per
organisation, with `effective_from` and a link to the audit log entry that created it), not a JSON blob.
Settings that are genuinely free-form (branding tokens) can stay JSON; settings that feed financial
calculations cannot.

### 2.5 Financial fact tables should be append-only, not soft-deleted (Section 9, 92, 123)

The spec lists "financial auditability" as priority #3 and asks for soft deletion "where commercially
appropriate" elsewhere. Those two things conflict for `purchase_invoices`, `purchase_invoice_lines`, and
`sales_facts`: a mutable row with a `deleted_at` flag means the history of *what the number used to be* is
gone the moment someone "corrects" it.

**Decision:** invoice/PO/sales fact tables are append-only. A correction is a new row referencing the
original via `corrects_id`, never an UPDATE to a posted financial row. Master data (suppliers, products,
users) can be soft-deleted normally — that distinction matters and the spec doesn't draw it.

### 2.6 AI-extracted contract terms need a hard gate, not just a "human verification status" column (Section 31, 41)

Section 31 says contract extraction needs a verification status; Section 78 says AI must never fabricate
financial values. But Section 41 (negotiation prep) and Section 29 (rebates) both consume contract terms.
If `contracts.extracted_rebate_terms` can be read by the rebate-calculation service before a human has
verified it, you've built exactly the fabrication risk Section 78 prohibits — just one hop removed.

**Decision:** unverified extraction lives in `contract_extractions` (a staging table). Nothing in
`rebates`, `opportunities`, or negotiation prep reads from it. Promotion to the fields that feed calculations
requires `verification_status = 'human_verified'` and is itself an audited action. Documented in `ADR-004`.

### 2.7 Consultant multi-org sessions are a specific leakage vector the spec doesn't address (Section 4.6, 55)

Section 4.6 wants external consultants attached to multiple organisations. If a JWT embeds "all orgs this
user belongs to + their role in each," any endpoint that reads role-from-token without re-checking
org-context on every request is one bug away from acting on the wrong tenant.

**Decision:** JWT carries `user_id` + a single `active_org_id` claim, nothing else. Switching organisations
is an explicit action that reissues a new scoped token; it is not a client-side dropdown over a fat token.
RLS session variable is set from `active_org_id`, so even a compromised/stale token can't read another org's
rows without a fresh, re-validated org-switch.

### 2.8 Rounding behaviour needs to be a written rule, not an implicit one (Section 68)

The spec correctly bans binary float for currency but doesn't specify a rounding mode. Tiered rebates and
VAT-inclusive/exclusive toggling compound rounding differences fast, and "close enough" is not an acceptable
answer when Finance is reconciling realised savings against the GL.

**Decision:** `ROUND_HALF_EVEN` (banker's rounding) is standard everywhere, applied at `NUMERIC(18,4)`
precision at rest, and calculation functions round only at the point of display/output, never mid-calculation.
Documented in `docs/analytics-methodology.md`.

### 2.9 Analytics at "millions of rows per tenant" will eventually need more than OLTP tables (Section 60)

ABC/Pareto/spend-by-category queries over millions of fact rows on the primary Postgres instance will
degrade as tenants scale, especially with RLS policies adding a predicate to every query. Not a Phase 1
problem. Flagging it now so it's a documented decision, not a surprise: Phase 5+ should introduce
materialized views refreshed by the worker (cheap, first move) with a documented escalation path to a
columnar/OLAP layer if row counts justify it later. Not built now — noted so nobody has to rediscover it.

## 3. Components

- **Backend** — FastAPI, Pydantic v2, SQLAlchemy 2.x (async), Alembic, PostgreSQL 16 (+pgvector), Redis.
- **Frontend** — Next.js (App Router), TypeScript, Tailwind, shadcn/ui, Recharts.
- **Workers** — Phase 1–3: FastAPI BackgroundTasks + job-status table. Phase 3+: Celery + Redis.
- **Object storage** — S3-compatible abstraction (`app/integrations/storage.py`), MinIO locally.
- **AI layer** — `LLMProvider` interface; Anthropic implementation first, others pluggable.
- **Auth** — JWT (short-lived access + refresh), Argon2id password hashing, RBAC + RLS.

## 4. Environments

Local dev via `docker compose up`: Postgres, Redis, MinIO, backend, worker, frontend. See `docker-compose.yml`.
Production target is provider-agnostic (Fly.io / Render / AWS all fit this shape) — no provider SDK calls in
application code, only in `integrations/`.

## 5. What Phase 1 actually delivers

Auth, organisations, memberships, RBAC, tenant isolation (app-layer + RLS), Docker dev environment, and a
working registration → login → dashboard-shell path. Everything else in this document describes where the
system is going, not what exists yet — see `implementation-plan.md` for the phase gate criteria.
