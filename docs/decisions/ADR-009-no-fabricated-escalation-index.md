# ADR-009: Escalation calculations require an externally-supplied index value, never invent one

**Status:** Accepted

**Context:** CPI-linked price-escalation clauses are common in SA supply agreements. The master
spec (Section 109) explicitly bans fabricating commodity/inflation correlations, and Section 108
says external benchmarks may only be shown when a legitimate licensed or public data source is
connected - which this platform doesn't have yet.

**Decision:** `calculate_escalated_price()` in `app/analytics/contract_calculations.py` takes the
applicable index/rate value as a required argument for `cpi_linked` contracts. It never looks one
up, estimates one, or defaults to a "reasonable" number - it raises `ValueError` if called for a
`cpi_linked` contract without one. The gap between "we know a clause is CPI-linked" and "we know
what CPI actually did" is real and must stay visible to the user, not papered over by the engine.

**Consequences:** Until a licensed CPI/inflation data source is connected (a future
`integrations/` module, not built here), CPI-linked escalations require manual entry of the index
value at calculation time. This is slower for the user than an automatic lookup, and correct.
