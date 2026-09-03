# ProcureIQ — Engineering Sprint Baseline

**Scope of this record:** from `UNIVERSAL_ENGINEERING_SPEC.md`'s adoption as the project's mandatory
root reference through the mobile-responsive layout consolidation and router verification audit.
Every figure below was re-checked fresh immediately before this document was written, not carried
forward from memory — the same discipline this whole sprint has been about applying to the product
itself.

## 1. What's genuinely verified vs. written-but-unexecuted

This distinction matters more than any single number below, so it's stated first, not buried.

- **`backend/tests_pure/`: 249 tests, actually executed, all passing.** Confirmed immediately
  before this document — not a stale count.
- **Everything else — the DB layer, every API route, the entire frontend — is syntax-checked and
  structurally verified, never executed.** No live Postgres, no `npm install`, no running server
  has existed anywhere in this sandbox at any point in this sprint. Every "verified" claim in this
  document means real, run static analysis (`py_compile`, bracket/JSX-tag balance, import-chain
  resolution, `node --experimental-strip-types --check`) — never a live HTTP response.
- Two real bugs were caught specifically *because* of this static-verification discipline, not
  despite it: a scripted line-numbered edit that silently corrupted `price_review_service.py`
  (caught by `py_compile`), and `dashboard-api.ts`'s `aiCopilotApi` export being silently swallowed
  by an adjacent edit (caught by import-chain tracing, not by Node's syntax checker, which passed
  the broken file without complaint).

## 2. Backend

**Migration chain: `0001` → `0014`, unbroken**, confirmed by walking every `revision`/`down_revision`
pair fresh. Five of those fourteen migrations were added during this specific sprint window
(`0010`→`0014`: comparison-basis provenance, consolidation review-notes/match-method, inventory
snapshots, management accounting tables) — `0001`–`0009` predate the spec's adoption and belong to
earlier phases of the broader build, not this sprint.

**18 ADRs on record** (`001`–`016`, `018`). `017` was never written — a genuine numbering skip
somewhere in this sprint, confirmed to be a harmless gap (nothing references it) rather than a
broken cross-reference, and left visible rather than silently renumbered to hide it.

### 2.1 Compliance findings closed this sprint (against `UNIVERSAL_ENGINEERING_SPEC.md`)

- **Finding 1**: `PriceReviewLine.comparison_basis` — a line where pack-size normalization
  succeeded on one side and failed on the other used to silently compare incompatible units.
  Now refuses and flags (`unit_mismatch`) rather than computing a misleading percentage.
- **Finding 2**: `EntrySource`/`PriceReviewMatchStatus` enums replacing 13 bare string-literal
  sites across `rebate_service.py`, `rebate_aggregation_service.py`, `price_review_service.py`,
  and two model files.
- **Finding 3**: `rate_pct`/`flat_rate_pct`/`escalation_rate_pct` range-bounded;
  `Currency` enum replacing unconstrained `str` across 13 sites in 7 schema files.

### 2.2 Major features built this sprint

- **Supplier Consolidation Graph** — `app/analytics/domain_graph.py` (pure, 20 tests: node
  dedup, weight fallback, raw-metric preservation, the full review-workflow state machine),
  `duplicate_detection_service.py`, `GET /opportunities/consolidation-graph`,
  `POST .../review`, migration for `match_method`/`review_notes` provenance columns.
- **Phase 5b (Inventory)** — `app/analytics/inventory_calculations.py` (pure, 19 tests, AST-verified
  determinism), `inventory_snapshots` (append-only, ADR-018), purpose-built ingestion/validation
  modules, `ADR-018` documenting the honest limits of the slow-moving-stock proxy (no
  `sales_facts` table exists, so it's a movement proxy, not a real turnover rate — stated as such
  in the code, not implied to be more precise than the data supports).
- **Management Accounting Engine** — `app/analytics/management_accounting.py` (pure, 27 tests):
  CIMA-style activity-based cost allocation, DSO/DIO/DPO/CCC working capital metrics, debtors/
  creditors aging buckets. `cost_allocation_rules` (mutable config), `cost_to_serve_ledger`/
  `working_capital_snapshots`/`aging_ledger_snapshots` (append-only). Demo seed
  (`app/db/seeds/management_accounting_demo.py`) grounded in real Gourmet Cape Distributors
  figures pulled directly from uploaded financial statements — see §4.
- **Canvas lens system** — three lenses (`app/analytics/canvas_lens.py`, 20 tests): Procurement
  (supplier → category → rebate leakage & contract renewal), Warehouse & Inventory
  (location → aging summary), Management Accounting (the full P&L-to-CCC node chain). A fourth
  lens ("Management Accounting" under its original framing) was explicitly *not* built early in
  this sprint when it would have required fabricated revenue/COGS data — only built once real
  data made it honest to do so.
- **AI Copilot intent router** — `app/ai/intent_router.py` (pure, 12 tests including adversarial
  SQL-injection- and prompt-injection-shaped inputs) is the actual safety mechanism behind
  `POST /ai/query`: a closed set of pre-approved intents, never a path from natural language to
  a live query.

## 3. Frontend

**19 routes**, all 8 sidebar links confirmed to resolve to a real, unique file (full audit
presented last turn — file resolution, no middleware conflicts, no duplicate routes, fresh
bracket-balance and deep import-chain checks across 27 traced files).

- **White-label gateway** (`/welcome`) — `HomeGateway.tsx`, `TruckTransition.tsx`,
  `lib/branding.ts` (centralized tenant-brand resolution, deployment-time env-var driven —
  explicitly *not* per-logged-in-tenant runtime branding, a distinction stated directly rather
  than left ambiguous). Real PPS Logistics assets wired in with verified exact pixel dimensions
  (truck 1774×887, worker 447×558), graceful icon fallback if assets are ever absent.
- **Mobile-responsive shared layout** — `app/dashboard/layout.tsx` now owns `Sidebar`+
  `DashboardHeader` once, for every `/dashboard/*` route; previously duplicated inline across 4
  separate files. `Sidebar.tsx` is a real slide-out drawer below `md:`, unchanged above it.
- **Logout and workspace-switcher** — both previously nonexistent anywhere in the app (confirmed
  by grep before either was built), now in `DashboardHeader.tsx`.
- **4 "Coming Soon" placeholder pages** (`spend-analytics`, `contracts`, `opportunities`,
  `settings`) — each states plainly what backend already exists behind it (`opportunities`
  notably already has a fully working API and one real UI, the consolidation graph) rather than
  presenting all four as equally unstarted.

## 4. Real data grounding

Two of Gourmet Cape Distributors' actual monthly reporting packs were read directly (June/July,
then August 2026) — real Net Sales, COGS, AR, AP, Inventory, and Cash figures, cell-referenced,
cross-checked where possible (the demo's West Coast delivery route's computed gross margin was
independently confirmed to match the source sheet's own pre-computed GP column exactly). The
legacy binary `.xls` Inventory Valuation Report could not be opened — no `xlrd`, no network to
install it — confirmed via file-signature metadata only, contents never fabricated or guessed at.

## 5. Known, explicitly tracked open items

Not silently deferred — each has a name and a reason:

- **`ADR-017`** — numbering gap, harmless, noted above.
- **Duplicate-SKU/supplier-consolidation review UI parity** — `DuplicateSkuFlag` has a review
  route; `SupplierConsolidationFlag` review buttons exist in the UI but the equivalent bulk
  workflow parity was never fully audited end-to-end.
- **Per-tenant runtime branding** — current gateway branding is deployment-time (env vars), not
  per-logged-in-organisation (would need a real DB table + API route, consistent with how every
  other tenant-scoped feature in this app works). Flagged, not silently built as if equivalent.
- **The Inventory Valuation Report** (`.xls`) remains unread — needs conversion to `.xlsx`/CSV or
  a different environment with `xlrd` available.
- **First real run has never happened.** `npm install`, `alembic upgrade head` against a live
  Postgres, and a running `next dev`/`uvicorn` pair have not occurred anywhere in this sprint.
  `docs/runbook.md` is the sequence for when that first run happens — treat it as genuinely
  first-time verification, not a formality, per its own stated framing.

## 6. Where things live

- Backend: `backend/app/` (routes in `api/v1/`, pure engines in `analytics/`, DB models in
  `db/models/`, migrations in `alembic/versions/`)
- Pure tests: `backend/tests_pure/` (249 tests, run via `python3 -m unittest discover -s tests_pure`)
- DB-dependent tests: `backend/tests/` (pytest, never executed here)
- Frontend: `frontend/src/` (`app/` routes, `components/`, `lib/` API clients, `types/`)
- Decisions: `docs/decisions/ADR-001` through `ADR-016`, `ADR-018`
- Runbook: `docs/runbook.md`
