# P-03 Foundation Candidate — F-03 + D-01 + P-03, CI-Pending

## What this is, precisely

**F-03 + D-01 + P-03 foundation only.** Built from a fresh extraction of the verified-clean
`procureiq-f03-d01-clean-ci-pending.zip`, with exactly the authoritative P-03 Patch A file set
overlaid on top — including Phase 1's event-level state-combination constraint and its full
172-case raw-SQL test matrix. Not a demo-ready state. Not a verified state.

## Migration 0021 has never run

No live PostgreSQL exists anywhere this was built. Confirmed structurally impossible, not merely
unattempted — checked directly against this exact sandbox earlier in this engagement.

## 172 raw-SQL P-03 test cases — written, unexecuted

Every one of these is a real, individually-discoverable pytest case (confirmed via direct `ast`
parsing of the parametrize lists, not estimated): the event-level state-combination constraint
across every measure and every reachable status, including a genuine-zero-amount case for every
one of the 10 states where a real amount can be recorded, every required-field-missing case,
every forbidden-field-populated case, and the confirmed-evidence-sufficiency checks for both
`expected_amount` and `realised_savings`. **None of these have run against a real database.**
CI evidence — not this ZIP's existence — is what would make any of them count as verified.

## CI is mandatory before merge, demo, or deployment

No exceptions. This foundation candidate existing, compiling cleanly, and passing every static
check available in this sandbox does not constitute CI evidence.

## Deferred, not started

Reporting/frontend work beyond what P-03 Patch A already touched remains outside this candidate's
scope — most notably `frontend/src/components/dashboard/TopSupplierIncreases.tsx`, which still
uses the `?? 0` false-zero pattern D-01 removed from `MetricRibbon.tsx`. Final regression tests
and genuine runtime/database verification also remain outstanding.
