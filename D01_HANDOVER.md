# D-01 Demo Hardening — F-03 + D-01, Clean, CI-Pending

## What this is

A complete F-03 project copy, rebuilt from the verified-clean F-03 handover ZIP (not from the
mixed sandbox tree), with exactly the audited D-01 changes overlaid on top. Confirmed by a full
recursive diff against an independently-extracted, untouched copy of the same F-03 baseline:
**exactly 12 differences, matching the D-01 file list precisely, nothing else.**

## Exact D-01 Files Changed/New (12 total)

**Modified (7)**: `.env.example`, `backend/app/core/config.py`, `backend/app/core/exceptions.py`,
`backend/app/services/auth_service.py`, `backend/app/main.py`, `backend/tests/test_auth.py`,
`frontend/src/app/page.tsx`

**New (5)**: `backend/app/db/seeds/demo_hardened_seed.py`,
`backend/tests_pure/test_registration_disabled_error.py`,
`backend/tests/test_demo_hardened_seed.py`, `frontend/src/lib/registration-guard.ts`,
`frontend/src/lib/registration-guard.test.ts`

**Deliberately not touched**: `.github/workflows/ci.yml` stays exactly as F-03 left it (two jobs,
`backend` and `frontend`) — the `migration-compatibility` job belongs to P-03 Patch A, not D-01,
and does not belong in this delivery. `tests/conftest.py` also untouched — `db_session` already
existed before F-03 (F-03's own tests use it), D-01 only reused it.

## P-03 Contamination Check — Explicit, Confirmed

- Zero files anywhere in this tree match `0021`, `financial_amount_events`,
  `financial_amount_status_events`, `FinancialAmountStatusEvent`, or `FinancialAmountEvidence` —
  searched directly, not inferred.
- Migration chain head is `0020` — confirmed by directory listing, not assumed.
- `ci.yml` has exactly two jobs — confirmed by direct grep, not assumed.

## Tests Executed vs. CI-Pending

| Test | Status |
|---|---|
| `tests_pure/` full suite (466 tests, 9 skips) | Executed fresh in the sandbox, prior turn |
| `registration-guard.test.ts` (4 tests) | Executed fresh via `node --test`, prior turn |
| `tsc --noEmit` on both D-01 frontend files | Clean, executed |
| The 7 DB/HTTP-dependent tests (registration-disabled 403, login-unaffected, default-unchanged,
  docs-404 real HTTP, docs-enabled-by-default, seed-idempotent, seed-fails-without-password) | **Written, not executed anywhere** — require `pytest`, `pytest-asyncio`, `pydantic-settings`, none available in this sandbox (confirmed by direct install attempt) |

## Status

**Not deployed. Not demo-ready.** Demo readiness is only honest once the 7 tests above report
green from a real CI PostgreSQL service — this ZIP existing does not constitute that proof.
