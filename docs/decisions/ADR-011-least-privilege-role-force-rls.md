# ADR-011: A least-privilege `procureiq_app` role, and `FORCE ROW LEVEL SECURITY`

**Status:** Accepted

**Context:** Writing the RLS integration test suite (`backend/tests/test_rls_integration.py`)
surfaced two compounding gaps that had been silently present since Phase 1:

1. Postgres RLS policies (`ENABLE ROW LEVEL SECURITY`) do **not** apply to the table owner or to
   superusers by default — only `FORCE ROW LEVEL SECURITY` makes a policy bind to the owner too.
   Every migration so far (0001-0003) used `ENABLE` only.
2. `docker-compose.yml` / `.env.example` define a single `procureiq` Postgres user used both to
   run migrations (which creates it as the owner of every table) *and* as `DATABASE_URL` for the
   running application. Migration 0001 already contained a `REVOKE UPDATE, DELETE ON audit_logs
   FROM procureiq_app`, guarded with `IF EXISTS` — but nothing had ever run `CREATE ROLE
   procureiq_app`, so that guard was silently no-opping. The role referenced in the very first
   migration never existed.

Put together: as configured, the application's own database connection is the table owner, RLS
policies don't bind to table owners without `FORCE`, and the one place a distinct low-privilege
role was assumed (audit-log immutability) was quietly not applying either. None of this raised an
error anywhere — it would only have shown up as a real breach, or never shown up at all.

**Decision:**
1. `procureiq_app` is now actually created (migration 0004), as a `LOGIN` role with only the DML
   grants it needs (`SELECT, INSERT, UPDATE, DELETE` on tenant-scoped tables; `SELECT, INSERT`
   only on `audit_logs` — no `UPDATE`/`DELETE`, making the Section 54 immutability requirement
   real rather than assumed). It is never granted table ownership.
2. Every RLS-enabled table also gets `FORCE ROW LEVEL SECURITY` in the same migration — defense
   in depth even though a genuinely non-owning role shouldn't need it, for the case where a future
   admin task or migration accidentally runs under a role that does own the tables.
3. `app/core/config.py` gets a new `database_url_app` setting; `app/db/session.py`'s runtime
   engine is built from it, not from `database_url` (which — renamed in intent, not in code, to
   avoid touching every existing reference — is now understood as the *migration/admin* URL,
   used only by `alembic/env.py`). The application, from this point forward, quite literally
   cannot connect to Postgres with owner-level privileges.

**Consequences:** Local dev now needs two sets of DB credentials instead of one — a small amount
of extra `.env` setup, documented in `.env.example` with inline comments explaining why. In
exchange, RLS actually does what every ADR since ADR-003 has claimed it does, instead of doing it
by coincidence of "the app happens to connect as a role RLS doesn't apply to being wrong in a way
nobody exercised yet." `docs/deployment-rls-checklist.md` item 3 already asked to verify
`BYPASSRLS`/superuser status — it's amended to also check `relforcerowsecurity` and that the
app's connection role is never the table owner, which is the check that would have caught this.
