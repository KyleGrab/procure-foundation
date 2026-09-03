# Phase 3 — Contract Lifecycle & Renewal Intelligence: Plan

## 1. Scope

Contract repository (verified terms only), expiry/renewal tracking, notice-period calculation,
auto-renewal alerts, and price-escalation calculations. This maps onto the original master spec's
Section 31-32 (Contract Intelligence / Contract Alerts) but is scoped tighter, matching the
addendum-spec pattern established in Phase 2: build the vertical slice, not the full breadth.

Out of scope for this delivery (documented, not silently dropped):
- Rebate management (original spec Section 29) - contracts can *reference* rebate terms as a
  verified summary field, but rebate threshold tracking/leakage calculation is its own phase.
- Supplier scorecards / performance data feeding SLA compliance - Phase 5+.
- Actual document text extraction running against a real model - no network in this environment,
  same constraint as Phase 2's negotiation brief.

## 2. Two reconciliations before writing code

### 2.1 "Clause parsing" is two different things, and only one of them is deterministic

Extracting terms from a contract PDF's free text (start date, notice period, escalation rate) is
an AI task - there's no reliable deterministic parser for arbitrary legal prose, and the master
spec itself requires human verification for exactly this reason (Section 31: "AI extracted
information must be reviewed against the signed agreement"). Building a "clause parsing engine"
that pretends to deterministically read a PDF would misrepresent what's actually possible.

**Decision:** split into two pieces, matching ADR-004's existing pattern:
- `app/analytics/contract_calculations.py` - genuinely deterministic, genuinely testable: given
  *already-known* structured terms (dates, notice period, escalation rate), compute status,
  notice deadlines, renewal dates, and escalated prices. This is real math with no ambiguity, and
  it's where this delivery's actual unit-tested engine lives.
- `app/ai/contract_extraction_service.py` - the AI-assisted path from a document to a first draft
  of those structured terms, writing only to `contract_extractions` (staging, per ADR-004), never
  read by the calculation engine until a human sets `verification_status = 'human_verified'`.

### 2.2 CPI-linked escalation must not let the calculator invent an index value

The master spec (Section 109) explicitly bans fabricating commodity/inflation correlations.
A CPI-linked escalation clause is common in real SA supply agreements, but "what was CPI last
quarter" is external data this platform has no licensed source for yet (Section 108's own
"only show external benchmarks when legitimate licensed data is connected").

**Decision:** `calculate_escalated_price()` takes the applicable index value as a required
argument for `cpi_linked` contracts - it is never looked up or estimated inside the function.
If no value is supplied, the function raises rather than silently defaulting to 0% or fabricating
a plausible-looking number. Calling code (service layer) must source that value from an explicit
user entry or a future licensed benchmark connector (Section 108) - never invent it upstream either.

### 2.3 Contract status: computed, not just stored

A contract's status (`active` / `notice_period_open` / `expiring_soon` / `expired` /
`auto_renewing`) is a function of today's date versus stored dates - if it's only written once at
creation, it silently goes stale. `classify_contract_status()` is a pure function of
`(today, expiry_date, notice_deadline, auto_renew)`, callable at read time. A `status` column is
still persisted for query filtering (an index-only "get all expiring_soon" query beats
recomputing on the fly for every list view), but it's refreshed by calling the same function - it
is never edited directly, and nothing here treats the stored value as authoritative over the
computed one.

## 3. Data model additions (migration 0003)

- **contracts** - verified fields only. `supplier_id`, `contract_number`, `title`, `start_date`,
  `expiry_date`, `notice_period_days`, `auto_renew`, `renewal_term_months`, `payment_terms_days`,
  `currency`, `escalation_type` (`none`/`fixed_percentage`/`cpi_linked`/`tiered`/`negotiated`),
  `escalation_rate_pct`, `rebate_terms_summary`, `sla_terms_summary`,
  `minimum_spend_commitment`, `status`, `status_calculated_at`, `source_file_storage_key`.
- **contract_extractions** - AI staging table per ADR-004. `contract_id` (nullable until
  promoted), `source_file_storage_key`, `extracted_fields` (JSONB: `{field: {value, confidence}}`),
  `extraction_model`, `prompt_version`, `verification_status`
  (`pending`/`human_verified`/`rejected`), `verified_by_user_id`, `verified_at`.
- **contract_alerts** - tracks which threshold alerts (180/90/60/30-day, notice deadline) have
  already fired for a contract, so the alert engine is idempotent rather than re-notifying every
  time it runs. `contract_id`, `alert_type`, `trigger_date`, `acknowledged_at`,
  `acknowledged_by_user_id`.

All three get RLS per ADR-003, same pattern as every migration so far.

## 4. What's genuinely testable here (same constraint as Phase 2)

`app/analytics/contract_calculations.py` is pure `datetime`/`Decimal`/stdlib - no DB, no network -
so it's actually unit-tested with `unittest`, not just written. Everything DB/API-touching
(`app/db/models/contract.py`, the migration, `services/contract_service.py`,
`api/v1/contracts.py`) is syntax-checked only, same honesty pattern as every phase so far: no
network in this sandbox to install SQLAlchemy/FastAPI or run Postgres.
