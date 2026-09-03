"""ADR-011: create the procureiq_app role for real (0001 assumed it existed and it never did),
grant it only the DML it needs, and add FORCE ROW LEVEL SECURITY to every RLS-enabled table from
0001-0003 so RLS actually binds even if a future connection somehow runs as the table owner.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-24
"""
from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# Every tenant-scoped table across every migration so far - kept as one explicit list here
# rather than querying pg_policies for tables with a tenant_isolation policy, so this migration's
# behavior doesn't silently change if a future migration adds a table without RLS by mistake
# (that omission should fail a review, not get quietly swept into a FORCE statement here).
_ALL_TENANT_SCOPED_TABLES = (
    "organisation_memberships", "organisation_settings", "locations",
    "suppliers", "price_reviews", "price_review_files", "price_review_mapping_templates",
    "price_review_lines", "opportunities",
    "contracts", "contract_extractions", "contract_alerts",
)

# Local-dev-only password, matching .env.example's DATABASE_URL_APP. Production deployments MUST
# rotate this (ALTER ROLE procureiq_app WITH PASSWORD '...') as part of their own secrets
# management - never rely on a value that ever appeared in a migration file or Git history for
# anything but a local docker-compose environment. See docs/deployment-rls-checklist.md.
_DEV_ONLY_PASSWORD = "procureiq_app_dev_only_rotate_in_production"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procureiq_app') THEN
                CREATE ROLE procureiq_app WITH LOGIN PASSWORD '{_DEV_ONLY_PASSWORD}';
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            EXECUTE format('GRANT CONNECT ON DATABASE %I TO procureiq_app', current_database());
        END $$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO procureiq_app")

    # DML only - no ownership, no DDL rights, no BYPASSRLS (that's a role attribute this
    # statement never grants, and CREATE ROLE above never requested it either).
    for table in _ALL_TENANT_SCOPED_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO procureiq_app")
        # FORCE matters even for a non-owning role: it's the difference between "RLS protects
        # this role because it happens not to own the table today" and "RLS protects this role
        # unconditionally" - ownership can change (a future migration re-run under a different
        # admin user, a manual ALTER TABLE OWNER TO during an incident) and this shouldn't be
        # the thing tenant isolation quietly depends on.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # organisations/users/refresh_tokens aren't tenant-scoped in the RLS sense (no
    # organisation_id / not FK'd to a single org) but the app still needs to read/write them.
    for table in ("organisations", "users", "refresh_tokens"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO procureiq_app")

    # Re-state audit_logs explicitly now that the role actually exists - 0001's REVOKE was a
    # silent no-op against a role that didn't exist yet (see ADR-011). Grant only what's needed
    # to write new entries; UPDATE/DELETE are never granted, making Section 54's immutability
    # requirement real.
    op.execute("GRANT SELECT, INSERT ON audit_logs TO procureiq_app")

    # Sequences backing every BIGINT IDENTITY column need USAGE for INSERT to work at all under
    # a non-owning role - easy to miss, and the kind of gap that only shows up as a runtime error
    # the first time someone tries to insert a row as procureiq_app.
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO procureiq_app")


def downgrade() -> None:
    for table in _ALL_TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM procureiq_app")
    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM procureiq_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM procureiq_app")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procureiq_app') THEN
                DROP ROLE procureiq_app;
            END IF;
        END $$;
        """
    )
