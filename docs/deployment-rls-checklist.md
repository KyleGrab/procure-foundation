# Deployment Readiness Checklist — Tenant Isolation

This is not a general deployment checklist (that's Phase 9's scope per `docs/implementation-plan.md`).
It's specifically what to verify before trusting Row-Level Security in any environment holding real
customer data — since a false sense of security here is worse than an admitted gap.

## 1. RLS is actually enabled, not just written in a migration

```sql
SELECT tablename, rowsecurity FROM pg_tables
WHERE schemaname = 'public' AND tablename IN (
  'organisation_memberships', 'organisation_settings', 'locations',
  'suppliers', 'price_reviews', 'price_review_files', 'price_review_mapping_templates',
  'price_review_lines', 'opportunities', 'contracts', 'contract_extractions', 'contract_alerts',
  'rebate_agreements', 'rebate_period_actuals', 'rebate_alerts', 'purchase_transactions',
  'purchase_orders', 'purchase_order_lines', 'purchase_invoices', 'purchase_invoice_lines',
  'goods_receipts', 'goods_receipt_lines', 'duplicate_sku_flags', 'supplier_consolidation_flags',
  'inventory_snapshots',
  'cost_allocation_rules', 'cost_to_serve_ledger', 'working_capital_snapshots', 'aging_ledger_snapshots'
);
```
Every row must show `rowsecurity = true`. If `alembic upgrade head` was run against a database
where these tables already existed from an earlier, pre-RLS migration, verify `ENABLE ROW LEVEL
SECURITY` didn't silently no-op (it won't error, but check the actual flag, don't assume).

## 2. The policy exists and references the right session variable

```sql
SELECT tablename, policyname, qual FROM pg_policies WHERE schemaname = 'public';
```
Every tenant-scoped table should have exactly one `tenant_isolation` policy, and `qual` should
reference `current_setting('app.current_org_id', true)`. A missing policy on `rowsecurity = true`
means the table is *locked to everyone* (RLS enabled, no policy = deny-all) — safer than a leak,
but check for it as a functional bug, not a security one.

## 3. The application's DB role cannot bypass RLS — three separate checks, not one

`BYPASSRLS` is a role attribute:
```sql
SELECT rolname, rolbypassrls FROM pg_roles WHERE rolname = 'procureiq_app';
```
Must be `false`. A superuser connection (`rolsuper = true`) bypasses RLS entirely regardless of
policies — confirm the application never connects as a superuser role in any environment past
local development.

**A third, easier-to-miss check (ADR-011):** RLS policies do not apply to the table owner unless
`FORCE ROW LEVEL SECURITY` is also set. This was actually wrong in this codebase from Phase 1
through Phase 3 — `ENABLE` was set, `FORCE` wasn't, and the app connected as the same role that
owned the tables, meaning RLS was not really protecting anything until migration 0004 fixed it.
Verify both conditions, not just one:
```sql
-- Every tenant-scoped table must show true in BOTH columns:
SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class
WHERE relname IN (/* full list in migration 0004 */) AND relkind = 'r';

-- procureiq_app must own none of them:
SELECT c.relname FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner
WHERE r.rolname = 'procureiq_app';
-- should return zero rows
```
`backend/tests/test_rls_integration.py` runs both checks automatically, plus a scratch-table
demonstration of why `FORCE` specifically matters — the fastest way to verify this in any new
environment is running that suite, not reading this checklist.

## 4. The session variable is set from the token, never from client input

Re-read `app/db/session.py:get_db` (Phase 1) before every deployment: `app.current_org_id` must
be set from `claims.active_org_id` (decoded, signature-verified JWT), never from a header, query
param, or path segment a client could set directly. This is the one place a correct RLS setup
still fails if the wiring above it is wrong — grep for `set_config` and confirm there's exactly
one call site.

## 5. Run the actual cross-tenant tests, don't just read this checklist

`backend/tests/test_tenant_isolation.py` and `backend/tests/test_price_review_tenant_isolation.py`
are the executable version of this checklist. They need a live Postgres (not run in the sandbox
that built this) — run them against every environment before data from more than one
organisation touches it:
```
pytest backend/tests/test_tenant_isolation.py backend/tests/test_price_review_tenant_isolation.py -v
```
Add a `test_contract_tenant_isolation.py` following the same pattern before Phase 3 contracts
data goes anywhere near a shared environment — not included in this delivery, flagged here so
it isn't forgotten.

## 6. Manual smoke test before first real customer data

Two organisations, two users, one browser session each (or two curl sessions with two tokens):
confirm Org A's token returns a 404 (not a 403 — see `docs/security.md` on why 404 is the
correct RLS-backed response) for every Org B resource ID you can construct, across suppliers,
price reviews, price review lines, contracts, and exports. A 403 instead of a 404 means the
resource's *existence* leaked even though its contents didn't — worth catching before it's habit.

## 7. What this checklist does not cover

Encryption at rest, backup access controls, VPC/network isolation, secrets rotation — all Phase 9
(`docs/implementation-plan.md`). This document is scoped to the one control this codebase leans on
hardest (RLS) precisely because Sections 2.1/3 of `docs/security.md` and ADR-003 treat it as load-
bearing, not decorative.
