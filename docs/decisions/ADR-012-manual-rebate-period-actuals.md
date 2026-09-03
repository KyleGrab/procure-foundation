# ADR-012: Manual period-actual entry for rebate calculations, not derived from existing tables

**Status:** Accepted (Phase 4 plan)

**Context:** Rebate leakage calculation needs actual cumulative spend/volume per supplier per
period, compared against threshold bands. No table in this codebase currently holds that: Phase
2's `price_review_lines` is a point-in-time price-list comparison, not a running purchase ledger;
the original master spec's `purchase_invoices` (append-only, ADR-006) is still unbuilt. Deriving
"actual spend this quarter" from data that doesn't represent that would be inventing a number
from an unrelated source, not a shortcut.

**Decision:** `rebate_period_actuals.actual_spend`/`actual_volume` are entered manually
(`entry_source = 'manual'`) in Phase 4, exactly mirroring ADR-008's fix for Phase 2's annual
quantity. When `purchase_invoices` lands, swapping the data source to real aggregated spend is a
value change on existing columns, not a schema change - the same shape of fix as ADR-008, kept
consistent on purpose so "we don't have the real ledger yet" doesn't get solved a different way
in every phase that runs into it.

**Consequences:** Every expected/earned/leakage figure in Phase 4 is only as reliable as the
period-actual entry behind it, same caveat as ADR-008. The UI must surface `entry_source =
'manual'` on every derived rebate figure with the same visibility ADR-008 required for manual
quantities - this is a carried-forward product requirement, not a new one.
