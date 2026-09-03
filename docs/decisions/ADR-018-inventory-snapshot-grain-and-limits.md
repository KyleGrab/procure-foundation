# ADR-018: Inventory snapshot grain, append-only design, and the honest limits of the
slow-moving-stock proxy

**Status:** Accepted

**Context:** Phase 5b (deferred since ADR-015) needed a real schema and calculation engine for
inventory opportunities - slow-moving stock, excess stock valuation, expiry risk. Three decisions
needed to be made explicitly rather than discovered as bugs later: what identifies an item (no
`products` table exists), whether snapshots are mutable or append-only, and how honest the
"slow-moving" signal can actually be given what data exists.

## Decision 1: item identity is (description, supplier_sku, location_id, snapshot_date), not product_id

No `products` table exists anywhere in ProcureIQ - deliberate since Phase 2
(`docs/phase2-price-review-plan.md` §2.3), restated at ADR-015. `inventory_snapshots` uses the
same free-text `description` + optional `supplier_sku` convention as every other purchase-adjacent
table (`purchase_invoice_lines`, `purchase_transactions`, `price_review_lines`) rather than
inventing a fourth identity convention or a `product_id` that references nothing.

**No DB-level UNIQUE constraint on the grain.** A rigid constraint would reject an entire messy
real-world upload outright on the first conflicting row. Instead,
`app.analytics.inventory_calculations.validate_snapshot_grain` (pure, tested) flags every
violation explicitly, so the ingestion layer can surface *which* rows conflict rather than the
database silently rejecting the whole batch or silently keeping one arbitrary row.

## Decision 2: append-only (ADR-006), not mutable

Caught during migration authoring, not before: the first draft of migration 0013 granted full
CRUD, treating a snapshot as an editable record. A stocktake count is a fact-in-time - "this was
the count on this date" - the same category as `purchase_transactions`/`purchase_invoices`/
`goods_receipts`, all already append-only. Corrected before the migration was finalized:
`corrects_id` self-FK added, `procureiq_app` grants restricted to `SELECT, INSERT` only.

## Decision 3: `calculate_days_since_last_movement` is an honest proxy, stated as one

No sales/consumption fact table exists in this schema (`sales_facts` is also still unbuilt, per
`docs/data-model.md`), so a real inventory turnover rate isn't computable from what this schema
will actually contain. What's built instead: comparing consecutive snapshots for the same grain
key and measuring days since quantity on hand last *decreased* - a restock (increase) is
explicitly not counted as movement, and does not reset the measurement. This is a slow-movement
*proxy*, not a turnover rate, and the function's own docstring says so rather than letting the
name imply more precision than the data supports. If `sales_facts` is ever built, this proxy
should be superseded by a real turnover calculation, not kept as the primary signal.

## Consequences

`calculate_excess_stock_value` and `classify_expiry_risk` both return `None`/`no_expiry_tracked`
rather than a fabricated figure when their required inputs (`reorder_level`/`unit_cost`,
`expiry_date`) are absent - same "no stated baseline, no figure" rule as PPV's
`reference_price_source` and `hard_saving`'s `baseline_methodology`. An organisation that doesn't
track reorder levels or expiry dates gets an honestly incomplete dashboard for those items, not a
guessed one.
