# Phase 3 Frontend — Contract Ingestion & Tracking: Component Specifications

Written as specifications rather than built pages in this delivery — Phase 1 and 2 built actual
`.tsx` files; Phase 3's frontend is scoped as specs so the backend (where the actual financial/
date logic and its real risk lives) got the verification effort. Building these out is
straightforward once there's a running backend to develop against — each spec below maps
directly to an existing route in `api/v1/contracts.py`.

## Routes

```
/contracts                          list + filter (status, supplier, expiring within N days)
/contracts/new                      upload document OR manual entry, buyer's choice up front
/contracts/new/extraction-review    only reached via the upload path - see below
/contracts/[id]                     overview: verified terms, status, derived dates
/contracts/[id]/escalation          escalated-price calculator
/contracts/[id]/alerts              alert history + manual "check now" trigger
```

## `/contracts` — List

**Data:** `GET /contracts?status=` (status recomputed server-side on every read — see ADR-010,
never trust a cached client-side status past the page load that fetched it).

**Columns:** Supplier, Title, Expiry Date, Notice Deadline (derived), Status (badge), Auto-Renew
(icon), Escalation Type. Default sort: soonest `notice_deadline` first — a contract 200 days from
expiry with a 180-day notice period is more urgent than one 60 days out with a 30-day notice
period; sorting by raw expiry date alone would get this backwards.

**Status badge colors** (matching `ContractStatus` values, not inventing a parallel taxonomy):
`active` neutral, `expiring_soon` amber, `notice_period_open` amber-bold, `auto_renewing` blue,
`expired` red.

**Filter bar:** status (multi-select), supplier (search), "expiring within" (30/60/90/180 days —
same thresholds as the alert engine, not arbitrary UI-only buckets).

## `/contracts/new` — Entry point

Two buttons, not a form: **"Upload a contract document"** and **"Enter terms manually"**.

- Manual path → a single form matching `ContractCreate` exactly (title, supplier, dates, notice
  period, auto-renew + term, escalation type + rate, currency, summaries). Client-side validation
  mirrors the Pydantic model's `model_validator` (`expiry_date > start_date`, `auto_renew`
  requires `renewal_term_months`, `fixed_percentage` requires a rate) so the error surfaces before
  a round-trip, not just after.
- Upload path → `POST` the file to storage, then `POST /contracts` (draft, minimal fields from
  filename/supplier picker) creating a placeholder contract, then trigger AI extraction
  (`app/ai/contract_extraction_service.py` — not wired to a route in this delivery, see
  `docs/phase3-contract-lifecycle-plan.md` §2.1), landing on the extraction-review screen once
  results come back.

## `/contracts/new/extraction-review` — AI extraction verification

**This is the screen ADR-004 exists for.** One row per extracted field:

| Field | Extracted Value | Confidence | Action |
|---|---|---|---|
| expiry_date | 2027-03-31 | 0.94 | ☐ Accept |
| notice_period_days | 90 | 0.81 | ☐ Accept |
| escalation_rate_pct | *(not found)* | — | *(manual entry required)* |

- Confidence below some threshold (reuse Phase 2's 0.80 review-recommended cutoff for
  consistency, not a new number) renders the row pre-unchecked and visually flagged, never
  pre-checked — the default for anything uncertain is "a human decided this," not "the system
  decided and the human get to veto."
- Fields the model listed in `unresolved_notes` render as empty inputs the user fills manually,
  labeled distinctly from extracted-and-unconfirmed fields — "not found" and "found but unsure"
  are different situations and must look different.
- Submit calls `POST /contracts/{id}/extractions/{extraction_id}/verify` with only the
  field names the user checked — matches `ContractExtractionVerify`'s itemized-promotion design
  exactly; there is no "accept all" button, on purpose.

## `/contracts/[id]` — Overview

**Data:** `GET /contracts/{id}` — note the response already includes `notice_deadline` and
`next_renewal_date` as derived fields (`ContractRead` schema), so this page never computes a date
itself; it only displays what the backend already worked out from
`app/analytics/contract_calculations.py`.

**Layout:** verified terms in a read-only summary card (title, dates, notice period, escalation),
a status timeline (start → notice deadline → expiry → renewal, today's position marked), and — if
`rebate_terms_summary`/`sla_terms_summary` are set — a "Verified Terms" panel labeled as
human-confirmed, distinct in styling from anything that still says "AI-suggested."

## `/contracts/[id]/escalation` — Escalated price calculator

**Data:** `POST /contracts/{id}/escalated-price` with `base_price` and `periods_elapsed`.

The form's shape depends on `escalation_type`, fetched from the contract first:
- `none` / `fixed_percentage`: just `base_price` + `periods_elapsed`.
- `cpi_linked`: **also requires `external_index_value_pct`, with an inline note explaining why**
  ("this platform doesn't have a licensed CPI feed yet — enter the applicable published rate").
  The field is not pre-filled with a guess, an average, or last year's number — per ADR-009, if
  the UI pre-filled a plausible-looking value here it would defeat the entire point of the backend
  refusing to invent one.
- `tiered` / `negotiated`: this endpoint rejects these types (spec: "tiered/negotiated
  escalations require a human-reviewed schedule, not a single formula") — the page shows the
  verified `rebate_terms_summary`/`sla_terms_summary` text instead of a calculator, with a note
  that these require manual reference to the signed schedule.

## `/contracts/[id]/alerts` — Alert history

**Data:** contract_alerts rows for this contract (no dedicated list-alerts route built in this
delivery — add `GET /contracts/{id}/alerts` alongside the existing
`POST /contracts/{id}/check-alerts` when this page is built) + a manual "Check for new alerts"
button calling the existing `POST` endpoint. Each fired alert shows its type, trigger date, and
acknowledgment status — acknowledging is a distinct action from the alert simply existing, so a
180-day warning doesn't silently imply someone has acted on it.

---

## Addendum: Phase 4 (Rebates) — not yet specified

Unlike Phase 3's routes above, Phase 4a/4b (`/rebates`, `/purchase-transactions`) have no frontend
component specification in this delivery — noted here rather than left silently absent, since
this file is where a reader would reasonably look for it. The natural home once written: a
`/rebates` list mirroring `/contracts`' pattern (status badges using `RebateStatus`, sorted by
days-to-period-close rather than a raw date for the same reason `/contracts` sorts by notice
deadline — see this file's `/contracts` list spec above), a rebate detail page showing the tier
bands and current progress (`amount_to_next_tier` from `RebatePeriodActualRead`, rendered as a
progress bar toward the next threshold), and a transaction-upload flow reusing the same
mapping-confirmation pattern as `/contracts/new`'s AI-extraction-review screen — except here it's
confirming a column mapping (spec Section 3), not verifying AI-extracted terms (ADR-004).
