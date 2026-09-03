# ADR-013: Phase 4 built as three escalating sub-phases, not one scope decision

**Status:** Accepted

**Context:** The three data-source options for rebate "actual purchase history" (manual entry,
minimal transactions table, full transactional ledger) aren't really alternatives to choose
between once - they're a natural progression, each one a strict upgrade of the data feeding the
same calculation engine. Building only the smallest was too little (doesn't fulfil "connect to
transactional line-item data"); building the largest first violates every scope-discipline
decision made since ADR-008.

**Decision:** Phase 4 ships in three sub-phases against the same `rebate_calculations.py` engine:
- **4a** - `rebate_agreements` (renamed from the plan doc's `rebates`, matching the terminology
  used when this was confirmed) + `rebate_period_actuals` fed by manual entry (ADR-012, as
  originally planned) + `rebate_alerts`.
- **4b** - `purchase_transactions`, a minimal append-only table (ADR-006's pattern - financial
  facts don't get mutated) with just enough fields to aggregate into a period's actual spend/
  volume, ingested via Phase 2's CSV/XLSX pipeline (`app/ingestion/`, generalized to accept a
  different canonical-field set rather than duplicated). `rebate_period_actuals.entry_source`
  gains a second value (`transaction_aggregation`) alongside `manual` - manual entry is never
  removed, only superseded per-period when real transaction data exists for that period.
- **4c** - the full `purchase_invoices`/PO/GRN-reconciliation ledger from the original master
  spec - explicitly NOT built in this delivery. Sized closer to a full phase on its own (it's the
  same scope Phase 2's ADR-008 and every prior phase deferred) - noted in
  `docs/phase4-rebate-leakage-plan.md` as future work with its own section, not silently dropped.

**Consequences:** `rebate_period_actuals` carries both possible provenances from the start
(`entry_source` was already designed as an enum in the 4a migration, not retrofitted in 4b) - the
schema doesn't change shape when 4b lands, only which rows populate which source. This is the
same "manual now, real source later, schema doesn't move" pattern as ADR-008/ADR-012 themselves,
applied one level up to the phase sequencing itself.
