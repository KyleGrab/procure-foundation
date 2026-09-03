# Phase 4 — Rebate Leakage & Financial Calculation Engine: Plan

## 1. Scope

Structured rebate terms (distinct from Phase 3's free-text `rebate_terms_summary`), tiered
volume-threshold tracking, expected-vs-earned-vs-received rebate calculation, and leakage
detection. Maps onto the original master spec's Section 29 (Rebate Management), analytics-
methodology.md §8 (already documents the formulas), and reuses the tiered-banding pattern already
built and tested in Phase 3 (`calculate_tiered_escalated_price`).

## 2. The reconciliation that has to happen before any code

**"Transactional line-item data" doesn't exist yet, and `price_review_lines` isn't it.**

Rebate calculation needs a running total: how much has this organisation actually spent with (or
bought from) a supplier *this quarter*, compared against the threshold bands in the rebate
agreement. `price_review_lines` (Phase 2) is a point-in-time comparison of two price lists — it
answers "did this SKU's price change," not "how much did we buy this period." The original master
spec's real transactional ledger (`purchase_invoices`, append-only, ADR-006) is still unbuilt —
deferred in every phase plan so far for the same scope-discipline reason.

This is the same shape of problem ADR-008 solved for Phase 2's annual quantity, and the same fix
applies:

**Decision (ADR-012):** `rebate_period_actuals.actual_spend` / `actual_volume` are entered
manually per period in this phase (`entry_source = 'manual'`), not derived from any existing
table. When `purchase_invoices` eventually lands, populating these from real aggregated spend is
a data-source change on existing columns, not a schema change — same shape as ADR-008's fix, on
purpose, so the pattern for "we don't have the real ledger yet" stays consistent across the
codebase rather than each phase inventing its own workaround.

**Also worth naming directly:** Phase 3's `contracts.rebate_terms_summary` is a human-verified
*summary string* — it was never meant to be calculated against, and doing so would mean
parsing free text for numbers, exactly the fabrication risk ADR-004/009 exist to prevent. Phase 4
introduces a separate, structured `rebates` table with real threshold bands and rates. A contract
can link to one or more `rebates` rows; the summary field stays what it always was — a
human-readable confirmation of what the document says, not an input to a formula.

## 3. Data model sketch (not yet migrated — this is the plan, not the build)

- **rebates** (tenant-scoped) — `supplier_id`, `contract_id` (nullable — not every rebate traces
  to a formally ingested contract), `rebate_type` (`fixed_percentage` / `tiered` / `volume` /
  `growth` / `fixed_amount` / `retrospective`), `period_type` (`quarterly` / `annual`), `bands`
  (JSONB list of `{threshold_spend, rate_pct}` — same shape as Phase 3's
  `TieredEscalationBand`, reused rather than re-invented), `flat_rate_pct`, `fixed_amount`,
  `currency`, `status` (`active` / `expired`), `created_by_user_id`.
- **rebate_period_actuals** (tenant-scoped) — `rebate_id`, `period_start`, `period_end`,
  `actual_spend`, `actual_volume`, `entry_source` (`'manual'` per ADR-012), `expected_amount`
  (calculated, stored for explainability — spec Section 105's pattern), `earned_amount` (set at
  period close, calculated), `received_amount` (only ever set from an actual credit-note/payment
  reference — never assumed equal to `earned_amount`, per analytics-methodology.md §8),
  `entered_by_user_id`.
- **rebate_alerts** (tenant-scoped) — mirrors `contract_alerts`' idempotency pattern exactly:
  `rebate_id`, `alert_type` (`threshold_approaching` / `period_closing` / `leakage_detected`),
  `trigger_date`, `acknowledged_at`, `acknowledged_by_user_id`.

All three get RLS (`ENABLE` + `FORCE`, per ADR-011 — that fix applies to every table from this
point forward, not just the ones that existed when it was found) in the migration that builds this.

## 4. Calculation engine (the genuinely testable part, same pattern as Phases 2-3)

`app/analytics/rebate_calculations.py` — pure `Decimal`/stdlib, no DB:

- `calculate_expected_rebate(actual_spend, rebate_type, bands|flat_rate_pct, fixed_amount)` —
  progressive, recalculated every time actual spend updates (spec Section 29's "approaching
  threshold" alert depends on this being live, not fixed-at-period-end).
- `calculate_progress_to_next_tier(actual_spend, bands) -> (next_threshold, amount_remaining)` —
  what actually drives the threshold-approaching alert; reuses the tier-lookup logic already
  proven in `calculate_tiered_escalated_price` rather than re-deriving it.
- `calculate_rebate_leakage(expected_amount, received_amount) -> Decimal` — analytics-
  methodology.md §8's formula, already documented, not yet implemented as code.
- `classify_rebate_status(expected, earned, received, period_closed) -> str` —
  `on_track` / `threshold_approaching` / `period_closed_awaiting_payment` / `leakage_detected` /
  `reconciled`.

Test plan mirrors Phases 2-3: worked examples from analytics-methodology.md §8, an edge case for
spend that hasn't reached the first tier yet (must return the base/no-rebate case, not error or
apply tier 1 retroactively), and a case where `received_amount` is set but doesn't match
`earned_amount` (the leakage case the whole feature exists to catch).

## 5. Open questions before implementation starts

1. **Alert cadence for `threshold_approaching`** — spec doesn't give a numeric trigger (unlike
   contract expiry's explicit 180/90/60/30-day bands). Proposing: fire when actual spend is
   within a configurable percentage (default 10%) of the next threshold, organisation-configurable
   via `organisation_settings` (ADR-004's existing pattern) — needs confirmation before it's built,
   since an arbitrary default here is a real business decision, not a technical one.
2. **What "period close" means operationally** — is it a user action (a button: "close Q1 2027 for
   Supplier X"), or purely calendar-driven? Affects whether `earned_amount` calculation is
   triggered by a route or a scheduled job (Phase 9 territory either way, but the *trigger*
   design differs).

## 6. Status — 4a and 4b BUILT, 4c deferred (see §7)

**Genuinely verified:** 35 new `unittest` tests when 4a/4b shipped (108 total then; see §7 below for
4c's additional 12, bringing the running total to 120 across Phases 2-4c, all passing) —
expected/leakage/tier-progress calculations, the confirmed 85%-within-30-days threshold alert
rule (both conditions required, not either alone), period-close timing, transaction aggregation,
and the purchase-transaction column mapping/validation. One real bug caught before shipping:
reusing Phase 2's `validate_rows` for transaction rows was confirmed, by actually running it, to
reject every row with a fabricated "Missing price" error (it checks fields transaction rows don't
have) — fixed with a purpose-built `validate_purchase_transaction_rows` instead of forcing a
reuse that didn't actually fit. `mapping.py`'s `suggest_mapping()` genuinely was made generic
(parameterized canonical fields/aliases) and reused correctly for 4b, confirmed against a
realistic transaction-file header row.

**Written and syntax-checked, not run:** DB models (`RebateAgreement`, `RebatePeriodActual`,
`RebateAlert`, `PurchaseTransaction`), migrations 0005-0006 (RLS `ENABLE`+`FORCE`+grants applied
from creation per ADR-011, not retrofitted), service layer, and FastAPI routes — same constraint
as every DB-touching module all session (no network for SQLAlchemy/FastAPI/Postgres here).
`purchase_transactions` is append-only at the grant level (`SELECT, INSERT` only for
`procureiq_app`), matching `audit_logs`' pattern and ADR-006's correction-via-new-row design.

## 7. Phase 4c — BUILT

Reversing the earlier deferral: built in this delivery. `purchase_orders`/`purchase_order_lines`
(mutable, status workflow), `purchase_invoices`/`purchase_invoice_lines` (append-only, ADR-006),
`goods_receipts`/`goods_receipt_lines` (append-only) - migration 0008, RLS `ENABLE`+`FORCE`+grants
applied from creation per ADR-011, append-only tables get `SELECT, INSERT` only for
`procureiq_app`, matching `purchase_transactions`'/`audit_logs`' precedent.

**Genuinely verified:** 12 more `unittest` tests (120 total across Phases 2-4c now, all passing) -
Purchase Price Variance (the literal implementation of `analytics-methodology.md` §5, documented
since Phase 0 and unbuilt until now), invoice line net-amount/tax calculations, and goods-receipt
variance. One real bug caught before shipping, not by running code (no DB here) but by checking
against this codebase's own established join pattern: an early draft of the new
`rebate_aggregation_service.py` referenced `PurchaseInvoiceLine.purchase_invoice`, an ORM
relationship that was never declared anywhere in this codebase (every join here uses an explicit
`.join(Target, Target.id == Source.fk)` form instead) - would have raised `AttributeError`
immediately if executed. Fixed to match the established pattern.

**The bigger design decision (ADR-014):** now that both `purchase_transactions` (4b) and
`purchase_invoices` (4c) can hold data for the same supplier/period, rebate aggregation needs a
precedence rule. Implemented as a waterfall (invoice data > transaction data > manual) in one
shared function (`app/services/rebate_aggregation_service.py`), called by both ingestion paths -
`purchase_transaction_service.py` was refactored to delegate to it rather than keep its own
now-competing aggregation logic, closing the exact drift ADR-014 exists to prevent.

**Written and syntax-checked, not run:** DB models, migration 0008, service layer
(`purchase_ledger_service.py`), and FastAPI routes (`/purchase-orders`, `/purchase-invoices`,
`/goods-receipts`) - same constraint as every DB-touching module all session. No correction
endpoint for a wrong invoice (referencing `corrects_id`) is built yet - noted, not silently
missing; the ingestion path and the PPV it triggers were Phase 4c's actual point.
