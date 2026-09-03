# ProcureIQ — Implementation Plan

Modular monolith, built in gated phases. Each phase has explicit acceptance criteria — nothing moves forward
on "looks done." No phase after 0 starts before the previous phase's tests actually pass (not "were written,"
*passed* — Section 120 of the spec is explicit about this and it's the right instinct).

## Phase 0 — Architecture (this delivery)
`docs/architecture.md`, `docs/data-model.md`, `docs/api.md`, `docs/security.md`,
`docs/analytics-methodology.md`, this file, `docs/decisions/ADR-*.md`, repo scaffold.
**Gate:** you've read this and either agree with the deviations in `architecture.md` §2 or tell me which
ones to revert before code depends on them — RLS and append-only fact tables in particular are expensive to
retrofit once data exists, cheap to build in now.

## Phase 1 — Foundation (started in this delivery)
Backend: FastAPI app, config, DB session (with RLS session-var wiring), Alembic, `users`,
`organisations`, `organisation_memberships`, `organisation_settings`, `audit_logs`, Argon2id auth, JWT
issue/refresh/org-switch, RBAC permission dependency, structured error format, `/health`, `/health/ready`.
Frontend: login, register, org setup, dashboard shell, auth state.
Docker: postgres, redis, minio, backend, frontend, worker (stub).
**Gate:** register → log in → invite a second user → confirm that user cannot see another organisation's
data even with a manually crafted request (this is the actual cross-tenant test, not a hypothetical one).

## Phase 2 — Master data
`suppliers`, `products`, `locations`, `supplier_products` CRUD. Import engine: CSV/XLSX upload, column
mapping (deterministic synonyms → fuzzy → AI-assisted suggestion → user confirmation), saved mapping
templates per org, staging-table validation, error/warning file download. Synthetic seed data generator
(`data/synthetic/`).
**Gate:** upload a real-shaped supplier master CSV with inconsistent headers, confirm mapping suggestions are
sane, confirm bad rows are rejected with a downloadable reason file, confirm re-uploading the same file is a
no-op (idempotency, Section 93).

## Phase 3 — Procurement data
`purchase_orders`, `purchase_invoices` (append-only), `goods_receipts`, `inventory_snapshots`, `sales_facts`
(append-only). Background processing moves to Celery here — this is the point where retries/concurrency
actually matter (see ADR-002). Product matching pipeline stages 1–4 (exact ID → normalized text → rule-based
token → fuzzy/RapidFuzz); stages 5–6 (embeddings, LLM-assisted) deferred to Phase 6 alongside the rest of AI.
**Gate:** import 12 months of synthetic purchase history at realistic row counts, confirm import job doesn't
block the API, confirm product matching queue surfaces genuinely ambiguous matches for human review rather
than either auto-merging or flooding the queue with obvious matches.

## Phase 4 — Flagship: Supplier Price Review — **BUILT** (delivered as an addendum spec's "Phase 2")
The first commercially demonstrable feature (spec Section 83). Upload old + new price list → column
mapping → product matching → low-confidence review → price movement calc (§1 of analytics-methodology) →
historical volume join → financial impact → margin impact (where sales data exists) → decision workflow
(accept/challenge/negotiate/investigate) → outcome tracking → cost-avoidance measurement.
**Gate:** matches the MVP definition in spec Section 115 items 6–13 end to end, on synthetic data with
intentionally planted anomalies (pack-size mismatches, duplicate SKUs, a price increase with no matching
prior line).

**Status:** the matching, normalization, calculation, ingestion, and Excel-export logic — the parts that
carry real financial/matching risk — are built and **genuinely verified**: 41 `unittest` tests actually
executed (not just written) in `backend/tests_pure/`, plus a full end-to-end run against generated synthetic
Cape Valley Foods data (`scripts/generate_synthetic_price_review_data.py` →
`scripts/demo_price_review.py`) that correctly classified every planted scenario (increases, decreases,
unchanged, new products, discontinued products, pack changes, SKU changes, description changes, and one
deliberately ambiguous variant pair) and produced a real, structurally-valid multi-sheet Excel export. Three
real bugs were found and fixed by actually running this against data, not by writing tests in isolation — see
`docs/phase2-price-review-plan.md` §3 for what that process surfaced.

The DB models, Alembic migration (with RLS per ADR-003), service layer, FastAPI routes, and frontend wizard
pages are written and syntax-checked, matching the same honesty pattern as Phase 1: this sandbox has no
network to install SQLAlchemy/FastAPI/pytest or run Postgres, so that layer has never actually executed.
`docs/phase2-price-review-plan.md` is the authoritative record of scope decisions (manual quantity entry —
ADR-008, module layout, phase-numbering reconciliation) and open risks for this delivery.

## Phase 5 — Opportunity engine
Spend analysis, ABC/Pareto, price variance, duplicate-SKU detection, supplier consolidation (with the
explicit non-assumption in spec §22 — flag it, don't auto-recommend), inventory opportunities (slow/excess/
expiry risk), savings register with the five-type distinction from analytics-methodology §7, savings
waterfall (identified → validated → approved → implemented → realised).
**Gate:** every generated opportunity has a stored baseline, methodology, and confidence — none are
generated as a bare number with no "how was this calculated" trail.

**Note:** rebate leakage calculation (originally scoped here under spec §29) was delivered ahead of
schedule as addendum "Phase 4" — see `docs/phase4-rebate-leakage-plan.md`. All three sub-phases are
built (4a manual entry, 4b minimal ledger, 4c full purchase order/invoice/goods receipt ledger).

**Phase 5 — engine, data model, service layer, and routes all BUILT.** Spend analytics (aggregation,
ABC classification, Pareto contributors) and the savings-register five-type discipline are genuinely
tested — 20 tests when the engine shipped, plus 12 more for the intent router this round, 152 total
across Phases 2-5 now, all passing. Price variance (spec §23, distinct from Phase 4c's PPV — see
`docs/phase5-opportunity-engine-plan.md` §2.2) is implemented and tested. `opportunities` extended with
the full spec §35 waterfall vocabulary (DB `CHECK` constraint, and now an actual service-layer guard —
`advance_waterfall_stage` rejects skipping a stage) and explainability fields;
`duplicate_sku_flags`/`supplier_consolidation_flags` tables built (migration 0009, RLS from creation).
`/spend-analytics`, `/opportunities`, `/savings-register` routes built and RBAC/RLS-scoped
(`docs/phase5-service-layer-and-ai-copilot-plan.md`). Duplicate-SKU detection and supplier-consolidation
flagging (reusing Phase 2's matching engine, per plan) are **not yet wired into a service** — the tables
exist, the matching engine they'd call already exists and is proven, the orchestration connecting them
doesn't yet. Inventory opportunities (spec §27) remain explicitly deferred as **Phase 5b** (ADR-015).

## Phase 6 — AI Copilot — **delivered ahead of schedule as part of Phase 5**
`LLMProvider` abstraction, prompt versioning (`app/ai/prompts/`), the permission-aware pipeline from
architecture.md §1 (intent → permission check → deterministic function → structured result → LLM
explanation), negotiation prep, contract-extraction staging table (ADR-004), human verification gate.
**Gate:** an adversarial test — ask the copilot a question designed to make it invent a number it doesn't
have data for — confirms it declines or asks for the missing input rather than fabricating a figure.

**Status:** the permission-aware intent pipeline this phase names is built — `app/ai/intent_router.py`
(the actual safety mechanism: a fixed, closed set of intents, each mapped to exactly one permission-checked
deterministic handler) is genuinely tested, 12 tests including SQL-injection- and prompt-injection-shaped
adversarial inputs, all refused correctly without a live model. `app/ai/copilot_service.py` wires it to
real handlers over `spend_analytics_service`/`rebate`/`contract` data and orchestrates the full NL→intent→
handler→structured-result→prose pipeline (`POST /ai/query`) — written and syntax-checked, never executed
(no network/LLM_API_KEY in this sandbox, same constraint as every AI-touching module since Phase 2).
`LLMProvider` (Anthropic + OpenAI) and `complete_structured` with Pydantic output parsing were already
built in Phase 3. Negotiation prep exists as two routes sharing one generator (ADR-016). Contract-extraction
staging/verification (ADR-004) was already built in Phase 3, ahead of this phase too.

**Not built:** the adversarial gate test above needs a live model to actually run — the router's *refusal*
behavior for out-of-scope classifications is tested (tests_pure/test_intent_router.py), but nothing here
has verified a real LLM's classification/summarization behavior end to end, because nothing in this
delivery ever could.

## Phase 7 — Contracts / Rebates — **contract lifecycle half BUILT** (delivered as an addendum "Phase 3")
Document upload, LLM extraction into `contract_extractions` only, human verification workflow, promotion to
`contracts` verified fields, rebate tracking against those verified terms only, contract-expiry alerts.

**Status:** contract repository, status/notice-period/renewal-date calculations, escalation calculations
(fixed/CPI-linked/tiered), and the alert-due engine are built and **genuinely verified** — 25 more
`unittest` tests, actually executed, in `backend/tests_pure/test_contract_calculations.py` (73 total
across Phases 2-4 now, all passing). Two real bugs were caught by running them, not just writing them — see
`docs/phase3-contract-lifecycle-plan.md`. Rebate *threshold tracking/leakage calculation* is now planned
as addendum "Phase 4" (`docs/phase4-rebate-leakage-plan.md`) — plan only, not yet built.

**Also fixed in this delivery (ADR-011), while writing the RLS integration suite:** RLS as configured
since Phase 1 (`ENABLE` without `FORCE`) did not actually protect against the application's own queries,
because the app connects with the same role that owns the tables. Migration 0004 creates a real
least-privilege `procureiq_app` role (Phase 1's migration had assumed one existed and it never did — the
audit-log immutability grant had been silently no-opping since Phase 1) and adds `FORCE ROW LEVEL SECURITY`
to every tenant-scoped table. `backend/tests/test_rls_integration.py` (pytest + testcontainers, needs
Docker — not run in this sandbox) tests the fix directly, including a scratch-table demonstration of why
`FORCE` matters, not just that it's present.

DB models, migration (RLS per ADR-003/011), service layer, and FastAPI routes are written and
syntax-checked, same honesty pattern as Phases 1-2. The AI extraction path
(`app/ai/contract_extraction_service.py`) and the negotiation-brief path (Phase 2) both now use
`LLMProvider.complete_structured` with Pydantic output models (`app/ai/schemas.py`) — neither has ever
actually called a model in this sandbox (no network). The ADR-004 staging→verification→calculation-engine
pipeline is directly tested end-to-end using real production code (not a re-implementation) in
`backend/tests_pure/test_adr004_staging_pipeline.py`. Frontend delivered as written component
specifications (`docs/phase3-frontend-specs.md`), not built pages.

## Phase 8 — Reporting
Executive dashboard, procurement dashboard, price-review dashboard, monthly management report (PDF via
WeasyPrint, Excel via openpyxl), consultant portfolio view.

## Phase 9 — Production hardening
Security review against `docs/security.md`, rate limiting verification, observability (structured logs,
Sentry, health checks under load), backup/restore drill (not just a documented plan — an actual restore
test), E2E (Playwright), load test at the row counts in spec §60, dependency vulnerability scan.

---

**On the "run the entire thing now" instinct:** this sandbox has no network access and none of
FastAPI/SQLAlchemy/Next.js pre-installed, so Phase 1 code below is written and syntax-checked, not
live-tested against a running Postgres — that step needs `docker compose up` in an environment with network
access (your machine, or Claude Code locally). I'm flagging that plainly rather than claiming a test passed
that didn't run, per spec Section 120.
