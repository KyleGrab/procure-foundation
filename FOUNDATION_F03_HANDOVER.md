# F-03 Foundation Repair — Handover

## Baseline

- Prior commit: `81f68f335ca25cb700adc4346bedbbfed9959227` ("feat: Gate A inventory reconciliation
  schema (0020), no fabricated data seeded")
- This handover's changes exist as **uncommitted working-tree changes** against that commit in
  this sandbox — confirmed via `git status --short` immediately before this ZIP was built.
- No further commit was made as part of this handover; that's a deliberate choice pending your
  review, not an oversight.

## Exact four files changed

1. `backend/app/core/exceptions.py` — added `EvidenceRequiredError`.
2. `backend/app/api/v1/logistics.py` — added the fail-closed guard, one new import.
3. `backend/tests/test_route_profitability_integration.py` — 3 pre-existing tests updated
   (their old assertions were no longer true), 5 new tests added.
4. `backend/pyproject.toml` — registered a new `integration` pytest marker (none existed
   anywhere in this codebase before this change) so database-dependent tests are visible and
   filterable rather than silently skipped.

Full unified diff for all four files is provided as a separate message alongside this ZIP.

## Purpose

`POST /logistics/route-profitability` computed and persisted `net_net_profit` directly from
caller-supplied `revenue`/`cogs`/`trade_spend` in the request body, with no evidence or
reconciliation behind those figures — confirmed by direct inspection, not assumed. No evidenced
revenue/COGS/trade-spend source exists anywhere in this codebase. The endpoint now fails closed
**unconditionally**, before any plausibility check, cost-pool calculation, or database write,
returning a structured `422 evidence_required` response instead.

Business decision (already made, recorded here, not re-litigated): route profitability is
evidenced-only. A future what-if/scenario calculator, if ever built, must be a separate,
explicitly estimated, non-persistent module that cannot feed management-accounting metrics — not
built as part of this repair.

## Tests passed (this exact moment, re-run fresh for this handover)

- `tests_pure/` full suite: **453 passed, 6 skipped** (all 6 trace to one cause — `pydantic_settings`
  missing in this sandbox, blocking `app.core.security` imports; all 6 are JWT/auth-decoding
  tests, none database-related).
- Two specific pre-existing pure tests re-confirmed independently, proving the plausibility and
  double-counting protections were never lost, only relocated in this file:
  `tests_pure/test_matching.py::test_zero_distance_with_real_drop_count_is_a_physical_impossibility`
  and
  `tests_pure/test_management_accounting.py::...test_net_of_waterfall_basis_with_nonzero_trade_spend_is_refused_not_silently_double_counted`.
- Cross-reference/drift checker: `0 issues`.
- All four changed files: confirmed compiling cleanly (`py_compile`).

## Tests written but not yet executed

All 5 tests marked `@pytest.mark.integration` in
`tests/test_route_profitability_integration.py` — `pytest`/`pytest-asyncio` are not installed in
this sandbox (confirmed by direct `import` attempt, not assumed), so none of these have actually
run anywhere, in this sandbox or otherwise, as part of this repair. This includes the two newly
implemented no-write and existing-record-unchanged tests, which have real bodies now (not
placeholders) but still require a live, disposable PostgreSQL to execute.

`TestEvidenceGateNeverCallsIngestion::test_ingest_route_profitability_is_never_called` is
genuinely database-free by design (calls the route function directly, bypassing FastAPI's
dependency injection) — but is in the same unexecuted state as the rest, for the same reason:
no `pytest` in this sandbox.

## Explicit statement

**Database and runtime verification of this repair remains entirely pending.** Nothing in this
handover has been proven against a live PostgreSQL database, a live running server, or a real
HTTP request. Every claim above is either static (file compiles, code inspected directly) or
pure-logic (the `tests_pure/` suite, which involves no database at all). This matches your own
framing: code hardened, runtime/database verification still to come.

## Unchanged scope

No ELC, imports, customs, or VAT work. No migration created or modified. No RLS policy touched.
No dependency added, removed, or version-changed. No frontend file touched. No new module
introduced beyond the one exception class directly required by this repair.
