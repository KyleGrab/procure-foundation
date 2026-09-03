"""Phase 5: extends opportunities with the five-savings-type discipline, waterfall status
vocabulary, and explainability fields (spec Sections 9/34/35/105-106); adds duplicate_sku_flags
and supplier_consolidation_flags (spec Sections 22/107). RLS ENABLE+FORCE+grants for the two new
tables from creation (ADR-011).

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_NEW_TABLES = ("duplicate_sku_flags", "supplier_consolidation_flags")


def upgrade() -> None:
    op.add_column("opportunities", sa.Column("savings_type", sa.String(32)))
    op.add_column("opportunities", sa.Column("baseline_value", sa.Numeric(18, 4)))
    op.add_column("opportunities", sa.Column("baseline_methodology", sa.String(32)))
    op.add_column("opportunities", sa.Column("confidence", sa.String(16)))
    op.add_column("opportunities", sa.Column("realised_savings", sa.Numeric(18, 4)))
    op.add_column("opportunities", sa.Column("approved_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id")))
    op.add_column("opportunities", sa.Column("approved_at", sa.DateTime(timezone=True)))
    op.add_column("opportunities", sa.Column("algorithm_version", sa.String(32)))
    op.add_column("opportunities", sa.Column("calculation_timestamp", sa.DateTime(timezone=True)))
    op.add_column("opportunities", sa.Column("source_dataset_ref", sa.String(255)))
    # spec Section 35's exact waterfall vocabulary, enforced at the DB, not just by convention -
    # existing rows already default to 'identified' (set since Phase 2) so this constraint is
    # satisfied for all current data without a backfill.
    op.execute(
        """
        ALTER TABLE opportunities ADD CONSTRAINT ck_opportunities_status_vocabulary
        CHECK (status IN ('identified','validated','approved','implementation','realised','rejected','expired'))
        """
    )

    op.create_table(
        "duplicate_sku_flags",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("supplier_id", sa.BigInteger(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("sku_a", sa.String(128)),
        sa.Column("description_a", sa.String(512), nullable=False),
        sa.Column("sku_b", sa.String(128)),
        sa.Column("description_b", sa.String(512), nullable=False),
        sa.Column("similarity_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("match_method", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="flagged"),
        sa.Column("reviewed_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_duplicate_sku_flags_org", "duplicate_sku_flags", ["organisation_id"])
    op.create_index("ix_duplicate_sku_flags_supplier", "duplicate_sku_flags", ["supplier_id"])

    op.create_table(
        "supplier_consolidation_flags",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("supplier_a_id", sa.BigInteger(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("supplier_b_id", sa.BigInteger(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("description_a", sa.String(512), nullable=False),
        sa.Column("description_b", sa.String(512), nullable=False),
        sa.Column("similarity_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("combined_spend", sa.Numeric(18, 4)),
        sa.Column("status", sa.String(32), nullable=False, server_default="flagged"),
        sa.Column("reviewed_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_supplier_consolidation_flags_org", "supplier_consolidation_flags", ["organisation_id"])

    for table in _NEW_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (organisation_id = current_setting('app.current_org_id', true)::bigint)
            """
        )
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procureiq_app') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO procureiq_app;
                END IF;
            END $$;
            """
        )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procureiq_app') THEN
                GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO procureiq_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    for table in reversed(_NEW_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("supplier_consolidation_flags")
    op.drop_table("duplicate_sku_flags")
    op.execute("ALTER TABLE opportunities DROP CONSTRAINT ck_opportunities_status_vocabulary")
    for column in (
        "savings_type", "baseline_value", "baseline_methodology", "confidence", "realised_savings",
        "approved_by_user_id", "approved_at", "algorithm_version", "calculation_timestamp",
        "source_dataset_ref",
    ):
        op.drop_column("opportunities", column)
