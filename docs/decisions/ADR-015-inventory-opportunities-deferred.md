# ADR-015: Inventory opportunities deferred as Phase 5b - no inventory_snapshots table yet

**Status:** Accepted

**Context:** Spec Section 27's slow-moving/excess/expiry-risk detection needs quantity-on-hand
data per product/location/date. Nothing built so far produces this - unlike spend analysis
(Phase 5's main scope), which Phase 4c's purchase ledger already provides for free, inventory
data has no natural byproduct anywhere in this codebase. Building it means a new
`inventory_snapshots` table plus a CSV/XLSX ingestion path - the same size of scope decision
`purchase_transactions` was for Phase 4b.

**Decision:** deferred as Phase 5b, tracked explicitly in `docs/phase5-opportunity-engine-plan.md`
rather than silently dropped from Phase 5's scope. Everything else in Phase 5 (spend analysis,
ABC/Pareto, price variance, duplicate-SKU, consolidation, savings register/waterfall) ships
without it, since none of it depends on inventory data.

**Consequences:** the Phase 5 "Intelligence" navigation area (spec Section 81) will be missing
its Inventory sub-page until 5b lands - noted as a known gap, not a silent one. Phase 4c was
deferred with the same reasoning in an earlier plan and then built the same session once the
foundational pieces (a supplier, an aggregation pattern) were already in place - inventory may
follow the same trajectory once spend analysis exists to draw the same "this is worth finishing
now" conclusion from, but that's a call for whoever picks this back up, not assumed here.
