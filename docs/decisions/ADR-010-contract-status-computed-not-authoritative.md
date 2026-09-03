# ADR-010: Contract status is a pure function of dates, persisted only for query performance

**Status:** Accepted

**Context:** A contract's lifecycle status (active/notice-period-open/expiring-soon/expired/
auto-renewing) depends entirely on today's date relative to stored dates. A status column set
once at creation and never revisited silently goes stale - a contract entering its notice period
doesn't fire an event, time just passes.

**Decision:** `classify_contract_status(today, expiry_date, notice_deadline, auto_renew)` in
`app/analytics/contract_calculations.py` is a pure function, callable at any time. A `status`
column is still persisted on the `contracts` table (an indexed "show me everything expiring
soon" query is worth the redundancy), but it is only ever written by re-running this function -
`status_calculated_at` records when, and nothing in the service layer treats the stored value as
more authoritative than a fresh call would produce. A scheduled job re-running this daily (Phase
9's background processing, not built in this delivery) is how the stored value stays current in
production; until then, the service layer recomputes on every read that needs it.

**Consequences:** One extra function call on reads that need status, in exchange for a status
column that can never silently lie about a contract that quietly crossed into its notice period.
