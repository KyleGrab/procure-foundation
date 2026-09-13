"""Phase 3: contracts, contract_extractions (AI staging, ADR-004), contract_alerts - plus RLS on
every new tenant-scoped table (ADR-003), same pattern as every migration so far.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-24
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_RLS_TABLES = ("contracts", "contract_extractions", "contract_alerts")


def upgrade() -> None:
    op.create_table(
        "contracts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("supplier_id", sa.BigInteger(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("contract_number", sa.String(64)),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("notice_period_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("renewal_term_months", sa.Integer()),
        sa.Column("payment_terms_days", sa.Integer()),
        sa.Column("currency", sa.String(3), nullable=False, server_default="ZAR"),
        sa.Column("escalation_type", sa.String(32), nullable=False, server_default="none"),
        sa.Column("escalation_rate_pct", sa.Numeric(9, 6)),
        sa.Column("rebate_terms_summary", sa.String(2048)),
        sa.Column("sla_terms_summary", sa.String(2048)),
        sa.Column("minimum_spend_commitment", sa.Numeric(18, 4)),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("status_calculated_at", sa.DateTime(timezone=True)),
        sa.Column("source_file_storage_key", sa.String(512)),
        sa.Column("created_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # A contract's status is meaningless without valid dates - enforced at the DB, not just
        # by the calculation engine assuming callers behave (belt-and-braces, matching this
        # project's general posture on financial/date invariants).
        sa.CheckConstraint("expiry_date > start_date", name="ck_contracts_expiry_after_start"),
        sa.CheckConstraint(
            "NOT auto_renew OR renewal_term_months IS NOT NULL",
            name="ck_contracts_auto_renew_requires_term",
        ),
    )
    op.create_index("ix_contracts_org", "contracts", ["organisation_id"])
    op.create_index("ix_contracts_supplier", "contracts", ["supplier_id"])
    op.create_index("ix_contracts_status", "contracts", ["status"])
    op.create_index("ix_contracts_expiry_date", "contracts", ["expiry_date"])

    op.create_table(
        "contract_extractions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("contract_id", sa.BigInteger(), sa.ForeignKey("contracts.id")),
        sa.Column("source_file_storage_key", sa.String(512), nullable=False),
        sa.Column("extracted_fields", postgresql.JSONB(), nullable=False),
        sa.Column("extraction_model", sa.String(64)),
        sa.Column("prompt_version", sa.String(32)),
        sa.Column("verification_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("verified_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_contract_extractions_org", "contract_extractions", ["organisation_id"])
    op.create_index("ix_contract_extractions_status", "contract_extractions", ["verification_status"])

    op.create_table(
        "contract_alerts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("contract_id", sa.BigInteger(), sa.ForeignKey("contracts.id"), nullable=False),
        sa.Column("alert_type", sa.String(32), nullable=False),
        sa.Column("trigger_date", sa.Date(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # See app.analytics.contract_calculations.determine_due_alerts - this is what makes the
        # alert engine idempotent even if it's accidentally run twice in one day.
        sa.UniqueConstraint("contract_id", "alert_type", name="uq_contract_alert_type"),
    )
    op.create_index("ix_contract_alerts_org", "contract_alerts", ["organisation_id"])
    op.create_index("ix_contract_alerts_contract", "contract_alerts", ["contract_id"])

    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (organisation_id = current_setting('app.current_org_id', true)::bigint)
            """
        )


def downgrade() -> None:
    for table in reversed(_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("contract_alerts")
    op.drop_table("contract_extractions")
    op.drop_table("contracts")
