"""K2: harden organisation_memberships RLS for auth flows (register/login/me/switch-org).

Two changes, both scoped to organisation_memberships only:

1. tenant_isolation is recreated with the identical permission semantics it already had, except
   the bare `current_setting('app.current_org_id', true)::bigint` cast is replaced with a
   NULLIF-guarded version. A real, reproduced defect (K2 investigation): once a custom GUC has
   been `SET LOCAL`'d at least once on a physical connection, Postgres returns '' (not NULL) for
   it after that transaction ends - and get_db (authenticated requests) and get_db_unauthenticated
   (register/login/me/switch-org) share one connection pool, so a pooled connection previously
   used by an authenticated request can carry that '' residue into a later unauthenticated one.
   `''::bigint` raises `invalid input syntax for type bigint: ""` - a hard SQL error, not a safe
   deny. NULLIF(..., '')::bigint turns that residue into NULL, which the policy already handles
   safely (organisation_id = NULL is neither true nor a match - a normal, safe deny).

2. A new, SELECT-only, PERMISSIVE self_membership_select policy is added, using the same
   NULLIF-guarded pattern against a new `app.current_user_id` GUC. Being FOR SELECT only, it
   cannot grant any INSERT/UPDATE/DELETE capability - Postgres RLS commands are scoped
   per-policy, and a SELECT policy has no bearing on write commands at all. Being PERMISSIVE
   (matching tenant_isolation, and the only mode used anywhere in this schema), it OR-combines
   with tenant_isolation for SELECT: a row is visible if it belongs to the active org OR belongs
   to the requesting user. This is what actually lets login/me/switch-org discover a user's own
   memberships before any organisation is "the active org" yet - tenant_isolation alone can never
   do that, since there is no active org yet at that point.

Deliberately does NOT retrofit any other tenant_isolation policy in the schema (organisation_settings,
locations, suppliers, ... all the rest) - those aren't part of any auth flow this defect touches, and
a repo-wide NULLIF retrofit is explicitly out of scope here (see docs/decisions and the K2 investigation
report) - it is real, separate, deferred security hardening, not required to close K2.

No role/grant/ownership change. procureiq_app keeps exactly the privileges migration 0004 gave it -
this migration only replaces the shape of one USING/WITH CHECK expression and adds one SELECT-only
policy on the same already-FORCE-RLS'd table.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-09
"""
from __future__ import annotations

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON organisation_memberships")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON organisation_memberships
        USING (
            organisation_id = NULLIF(current_setting('app.current_org_id', true), '')::bigint
        )
        """
    )

    # FOR SELECT only: cannot expand INSERT/UPDATE/DELETE capability regardless of the USING
    # expression's shape - Postgres scopes a policy's applicable commands strictly by its FOR
    # clause. PERMISSIVE (the default, and the only mode used anywhere in this schema) so it
    # OR-combines with tenant_isolation for SELECT rather than replacing or narrowing it.
    op.execute(
        """
        CREATE POLICY self_membership_select ON organisation_memberships
        FOR SELECT
        USING (
            user_id = NULLIF(current_setting('app.current_user_id', true), '')::bigint
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS self_membership_select ON organisation_memberships")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON organisation_memberships")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON organisation_memberships
        USING (organisation_id = current_setting('app.current_org_id', true)::bigint)
        """
    )
