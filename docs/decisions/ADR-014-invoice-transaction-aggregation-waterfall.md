# ADR-014: Phase 4c coexists with 4b via an aggregation-source waterfall, not a replacement

**Status:** Accepted

**Context:** Phase 4c builds the real `purchase_invoices`/`purchase_invoice_lines`/`goods_receipts`
ledger the original master spec always described. Phase 4b's `purchase_transactions` (minimal,
no PO/GRN linkage) already exists and already feeds `rebate_period_actuals` aggregation. Once 4c
exists, both tables can have data for the same supplier/period, and `aggregate_transactions_for_period`
(the pure function both would call) doesn't know which one to trust more.

**Decision:** Not every organisation using this platform will have formal PO/invoice/GRN
discipline from day one — `purchase_transactions` stays as a legitimate lighter-weight ingestion
path (e.g., for suppliers an organisation hasn't formally onboarded into PO-based procurement
yet), not a deprecated stepping-stone. Rebate period aggregation uses a waterfall, evaluated per
period, per supplier:

1. **`invoice_aggregation`** — if `purchase_invoice_lines` exist for the period, use them. An
   actual invoice is the most authoritative record of what was actually billed.
2. **`transaction_aggregation`** — else, if `purchase_transactions` exist for the period, use
   those (Phase 4b, unchanged).
3. **`manual`** — else, the ADR-012 fallback.

This waterfall logic lives in exactly one place (`app/services/rebate_aggregation_service.py`),
called by both the invoice-ingestion path (4c) and the transaction-ingestion path (4b) rather than
each computing its own precedence - the same "one function, one source of truth" rule as every
calculation module this session.

**Consequences:** `rebate_period_actuals.entry_source` gains a third value
(`invoice_aggregation`) - no schema change, same column, matching ADR-013's own pattern one level
further. A period that was aggregated from `purchase_transactions` gets silently upgraded to
`invoice_aggregation` the first time real invoice data lands for that period, and never downgrades
back - once a more authoritative source exists for a period, the less authoritative one is never
trusted again for it, even if a later transaction upload happens to touch the same period.
