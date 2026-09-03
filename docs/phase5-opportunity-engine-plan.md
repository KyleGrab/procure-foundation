# Phase 5 — Opportunity Engine: Plan

## 1. Scope

Spend analysis, ABC/Pareto, price variance (inconsistent pricing across purchases — distinct from
Phase 4c's PPV, see §2.2), duplicate-SKU detection, supplier consolidation flagging (never
auto-recommended — spec §22's explicit non-assumption), inventory opportunities, and a proper
savings register with the five-type distinction (analytics-methodology.md §7) and the identified→
validated→approved→implemented→realised waterfall (spec §35).

## 2. What's different about this phase: real data already exists

Every prior phase either had no transactional data to analyze (Phase 2's price review is a
snapshot comparison, not a ledger) or had to invent a manual-entry workaround (ADR-008, ADR-012)
because the ledger didn't exist yet. Phase 4c changed that — `purchase_invoice_lines` and
`purchase_transactions` are real, queryable spend data. Phase 5 is the first phase that gets to
build directly against them rather than deferring or working around a gap.

### 2.1 Spend analysis is scoped to what's actually trackable

No `products` table exists (Phase 2's ADR reasoning, restated in every phase since: price review
and the purchase ledger both operate on free-text `supplier_sku`/`description`, not a normalized
catalog). "Spend by category" is buildable via `suppliers.category` (spend by *supplier* category);
"spend by product" groups by the free-text SKU/description pair, same as Phase 2's matching
engine already does — not a joined product dimension. This isn't a new gap, it's the same one
every phase has consistently declined to fill, applied consistently here too.

### 2.2 Price variance ≠ Purchase Price Variance (already built)

Spec §23's "price variance" (different branches paying different prices for the same SKU;
invoice price differs from PO price; a supplier increase applied inconsistently across orders) is
a **different question** from Phase 4c's PPV (a single invoice line vs. one reference price).
Price variance here means: across every purchase of the same SKU+supplier within a period, are
the prices paid actually consistent? `calculate_price_consistency()` (new, this phase) takes a
list of (price, date, location) tuples for one SKU+supplier and flags the spread — it does not
duplicate PPV, it answers a question PPV structurally can't (PPV needs a stated reference price;
this needs none, it just compares purchases against each other).

### 2.3 Duplicate-SKU and supplier-consolidation reuse Phase 2's matching engine, not a new one

Both are fundamentally "are these two things the same product," which is exactly
`app/matching/` (normalize, pack_parser, fuzzy_matcher, scorer) — proven across 41 tests since
Phase 2. Duplicate-SKU detection runs it within one supplier's own SKU list; consolidation runs it
across different suppliers' SKU lists for the same organisation. No new matching logic - new
*orchestration* (which SKU sets to compare) over the existing engine.

### 2.4 Inventory opportunities need a decision this phase can't make silently

Slow-moving/excess/expiry-risk detection needs `inventory_snapshots` (quantity on hand, per
product, per location, per date) — nothing in this codebase produces or stores that, and there's
no natural byproduct of Phase 1-4c's work that gives it away for free (unlike spend analysis,
which purchase_invoice_lines/purchase_transactions already provide). Building it means a new
minimal snapshot table plus an ingestion path (CSV/XLSX upload, reusing `app/ingestion/` again) -
a scope decision the same size as Phase 4b's `purchase_transactions` was.

**Decision for this delivery:** deferred as **Phase 5b**, tracked explicitly (not silently
dropped, same discipline as Phase 4c's original deferral before it got built anyway). Phase 5
(this plan) ships spend analysis, ABC/Pareto, price variance, duplicate-SKU, consolidation, and
the savings register/waterfall - everything buildable against data that already exists.

## 3. Data model

- **`opportunities` (extend, not replace)** — the table from Phase 2 already exists with a
  minimal field set. This phase adds the fields spec §9/§105/§106 always wanted:
  `savings_type` (`hard_saving`/`cost_avoidance`/`working_capital`/`margin_protection`/
  `efficiency_saving` — analytics-methodology.md §7's five types, one per opportunity, never
  blended), `baseline_value`, `baseline_methodology`, `confidence`, `algorithm_version`,
  `calculation_timestamp`, `source_dataset_ref`, `realised_savings`, `verification_status`
  (`identified`/`validated`/`approved`/`implementation`/`realised`/`rejected`/`expired` — spec
  §35's exact waterfall stages), `approved_by_user_id`, `approved_at`.
- **`duplicate_sku_flags`** (new) — `product_a_ref`, `product_b_ref` (both free-text
  supplier_sku+description pairs, not FKs to a nonexistent product table), `similarity_score`,
  `match_method`, `status` (`flagged`/`confirmed_duplicate`/`rejected`), reviewed_by/at - human
  confirmation required before anything downstream treats two SKUs as the same (same
  never-silently-merge principle as Phase 2's product matching).
- **`supplier_consolidation_flags`** (new) — same shape, but across suppliers:
  `product_ref`, `supplier_a_id`, `supplier_b_id`, `similarity_score`, `combined_spend`, `status`.
  Explicitly a flag, never an auto-generated opportunity — spec §22 requires a human to weigh
  service risk/geographic coverage/resilience before consolidation is even proposed as an idea.

RLS `ENABLE`+`FORCE`+grants from creation (ADR-011/003), same as every table since migration 0004.

## 4. Calculation engine

`app/analytics/spend_analytics.py` (new) — pure, no DB:
- `calculate_spend_by_supplier/by_month/by_sku(...)` — aggregation over already-fetched rows,
  same shape as `aggregate_transactions_for_period` (Phase 4b/c).
- `calculate_abc_classification(spend_items, thresholds)` — cumulative-percentage banding
  (A/B/C), organisation-configurable thresholds, not hardcoded 80/15/5.
- `calculate_pareto_contributors(spend_items, target_pct=0.8)` — the "top N accounting for 80%"
  figure the spec explicitly asks for as its own view, distinct from ABC banding.
- `calculate_price_consistency(price_observations)` — spec §23, per §2.2 above: returns spread,
  flagged outliers, and whether the variance is worth surfacing (a configurable threshold, not a
  fixed one - a R2 spread on a R4 item and a R2 spread on a R4,000 item are not the same signal).

`app/analytics/savings_register.py` (new) — the five-type discipline as code, not just a column
constraint: a function per savings type that requires exactly the inputs that type needs (e.g.
`working_capital` requires day-count and daily-spend, not a baseline unit cost) - it should be
structurally awkward to compute a `hard_saving` figure using `working_capital`'s inputs.

Duplicate-SKU/consolidation don't get new calculation functions - they call
`app.matching.scorer.find_best_match` and friends directly, orchestrated by the service layer.

## 5. What's next

Build order: migration extending `opportunities` + new duplicate/consolidation tables → spend
analytics engine + real `unittest` tests → savings register engine + tests → service layer
(spend queries, duplicate/consolidation flagging orchestration, opportunity lifecycle) → routes.
Phase 5b (inventory) gets its own plan once this ships, matching Phase 4's precedent.
