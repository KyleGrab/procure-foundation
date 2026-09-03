# Phase 5 — Service Layer, Routes & Safe AI Copilot: Plan

## 1. Scope

Three REST route groups over Phase 5's already-built, already-tested engine
(`app/analytics/spend_analytics.py`, `app/analytics/savings_register.py`): `/spend-analytics`,
`/opportunities`, `/savings-register`. Then the Safe AI Copilot (`/api/v1/ai/query`) and a
generalized negotiation brief. Same rule as every phase so far: the route/service layer is
syntax-checked only (no network for SQLAlchemy/FastAPI/Postgres in this sandbox); anything that
can be pure logic is built to actually run, and does.

## 2. Reconciling the negotiation brief (not duplicating it)

`app/services/negotiation_brief_service.py` already has everything except a second data source:
`generate_brief(provider, context)` calls `LLMProvider.complete_structured` with
`NegotiationBriefOutput` (already generic - summary/priority_items/challenge_points/etc. don't
mention price reviews anywhere in their shape). Only `build_negotiation_brief_context()` is
price-review-specific, because it only knows how to read `PriceReviewLine`s.

**Decision:** add `build_negotiation_brief_context_from_spend()` - same output type
(`NegotiationBriefContext`), sourced from Phase 5's spend analytics (`aggregate_spend`,
`calculate_price_consistency`) plus a supplier's contracts/rebates where they exist, instead of a
price review. `/api/v1/ai/negotiation-brief` (new, general-purpose) calls this; the existing
`/price-reviews/{id}/negotiation-brief` keeps calling the original builder. Both then call the
same `generate_brief()` - one prompt template, one output schema, one LLM-calling function, two
ways of assembling the verified input it's given. This is the same shape of fix as ADR-014
(shared aggregation waterfall, not two competing implementations).

## 3. REST layer design

Same conventions as every route group since Phase 1: thin routes, `require_permission`
dependency per route, business logic in `services/`, tenant scoping automatic via `get_db`
(the RLS session variable is set once per request from the validated token - a route never
touches `organisation_id` directly except to pass `claims.active_org_id` into a service call).

- **`/spend-analytics`** — read-only. `GET /spend-analytics/by-supplier`,
  `/by-sku`, `/abc-classification`, `/pareto`, `/price-variance/{supplier_id}/{sku}`. Each pulls
  rows from `purchase_invoice_lines`/`purchase_transactions` (ADR-014's same waterfall
  preference - invoice data first) and calls the relevant pure function from
  `spend_analytics.py`. `VIEW_FINANCIALS` permission.
- **`/opportunities`** — the existing Phase 2 minimal CRUD, extended: `POST` gains the Phase 5
  fields (`savings_type`, `baseline_methodology`, `confidence`), `POST /{id}/approve` transitions
  the waterfall stage (`APPROVE_OPPORTUNITIES` permission, sets `approved_by_user_id`/`approved_at`),
  `POST /{id}/realise` records `realised_savings`.
- **`/savings-register`** — `GET /savings-register/waterfall` (calls
  `calculate_savings_waterfall` over the org's opportunities), `GET /savings-register?savings_type=`
  filtered list. Reads the same `opportunities` table as `/opportunities` - a reporting view over
  it, not a separate table, matching how `savings_type` was added to `opportunities` rather than
  creating a parallel `savings` table in migration 0009.

## 4. Safe AI Copilot pipeline

Literal implementation of `docs/architecture.md` §1's pipeline, which has existed as a diagram
since Phase 0 and nothing until now has actually built it:

```
NL question -> intent classification (LLM, constrained to a fixed enum)
            -> intent_router.dispatch() [PURE, no LLM, no DB write path]
            -> pre-approved analytics/service function [deterministic]
            -> structured result
            -> LLM turns result into prose [LLM, given only the structured result]
```

**The part that makes this safe, and the part this delivery actually builds and tests:**
`app/ai/intent_router.py` is a pure dispatch table - `Intent` enum (a fixed, closed set:
`spend_by_supplier`, `spend_by_sku`, `abc_classification`, `pareto_contributors`,
`price_variance_check`, `rebate_status`, `contract_expiry_check`, `unsupported`), each mapped to
exactly one permission-checked handler function. `dispatch()` raises if the intent isn't in the
table - there is no fallback path where an unrecognized intent gets passed through as free text
to anything that touches the database. The LLM's classification step can be wrong or refuse to
answer; it cannot cause an unapproved query to run, because the router doesn't know how to run
one - this is enforced by what functions exist in the dispatch table, not by a runtime check that
could have a gap.

**What still needs a live model (not run in this sandbox, same as every AI-touching module so
far):** the classification call itself (NL question -> `Intent` enum, via
`complete_structured`), entity extraction (e.g. "Cape Valley Foods" -> a supplier lookup - the
LLM extracts the *name*, a deterministic DB lookup resolves it to an ID, the LLM never sees or
produces an ID/SQL fragment), and the final structured-result-to-prose step.

## 5. What's genuinely testable here

`app/ai/intent_router.py`'s dispatch table and rejection behavior — pure, no LLM, no DB — tested
with real `unittest` tests, same as every guardrail module this session (mirrors
`app.ai.extraction_guardrails`'s pattern exactly: ADR-004's gate was pure and tested, this is the
same idea applied to intent dispatch). Everything downstream of an LLM call (classification,
entity resolution, prose generation) is written and syntax-checked, not executed - no network
here, same constraint since Phase 2's negotiation brief.

## 6. Status update — REST layer, AI Copilot, and frontend dashboard all BUILT

**Backend:** all three route groups (`/spend-analytics`, `/opportunities`, `/savings-register`), the
Safe AI Copilot (`/ai/query`, `/ai/negotiation-brief`), duplicate-SKU/supplier-consolidation
orchestration (reusing Phase 2's matching engine), and month-over-month/top-price-increase spend
views are built. 156 `unittest` tests passing (12 for the intent router alone, including
SQL-injection- and prompt-injection-shaped adversarial inputs). Two real bugs caught before
shipping by checking against this codebase's own established patterns (not by running code - no
network here): a reference to `PriceReviewLine.price_review`, an ORM relationship never declared
anywhere in this codebase, and a frontend button wired to call a service function
(`review_duplicate_sku_flag`) with no route exposing it yet - the route was added rather than left
as a TODO. The equivalent review route for supplier-consolidation flags does *not* exist yet -
left honestly unresolved (the frontend disables those buttons with an explanatory tooltip rather
than calling something that isn't there).

**Frontend:** a real Next.js dashboard (`app/dashboard/page.tsx` + `components/dashboard/*` +
`components/ui/*` hand-written shadcn-compatible primitives, since the shadcn CLI needs network
this sandbox doesn't have) matching the dark-mode visual spec exactly - colors, layout
percentages, component hierarchy. Verified two ways given the constraint that `npm install` can't
run here: `lib/api.ts` and `lib/dashboard-api.ts` (pure TypeScript, no JSX) pass genuine syntax
checks via `node --experimental-strip-types --check` - not eyeballed, actually run. The `.tsx`
component files can't be checked that way (Node doesn't transform JSX), so those got
bracket-balance checks, JSX tag-balance checks, and a full cross-check that every import resolves
to a real file and export - all clean, but this is not the same guarantee `tsc`/`next build`
would give, and is stated as such rather than implied to be equivalent.

Two data gaps are shown honestly in the UI rather than faked: "Gross Margin Erosion Rate" reads
"No data" (no selling-price data exists anywhere in this schema to compute it), and the spend
breakdown donut shows "Uncategorised" (no product-category dimension exists - the same deliberate
decision as every phase since Phase 2's product-catalog reconciliation, `docs/phase2-price-review-plan.md` §2.3).
