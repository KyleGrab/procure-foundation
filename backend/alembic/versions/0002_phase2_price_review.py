"""Phase 2: suppliers, price reviews, price review files/lines, mapping templates, opportunities
- plus RLS policies for every new tenant-scoped table (ADR-003) and the checksum uniqueness
constraint that implements spec Section 2's "prevent accidental duplicate processing" and
Section 93's idempotency requirement.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_RLS_TABLES = (
    "suppliers",
    "price_reviews",
    "price_review_files",
    "price_review_mapping_templates",
    "price_review_lines",
    "opportunities",
)


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("supplier_code", sa.String(64)),
        sa.Column("legal_name", sa.String(255), nullable=False),
        sa.Column("trading_name", sa.String(255)),
        sa.Column("tax_number", sa.String(64)),
        sa.Column("registration_number", sa.String(64)),
        sa.Column("payment_terms_days", sa.Integer()),
        sa.Column("lead_time_days", sa.Integer()),
        sa.Column("minimum_order_value", sa.Numeric(18, 4)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="ZAR"),
        sa.Column("category", sa.String(128)),
        sa.Column("account_manager", sa.String(255)),
        sa.Column("email", sa.String(320)),
        sa.Column("phone", sa.String(32)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_suppliers_org", "suppliers", ["organisation_id"])

    op.create_table(
        "price_reviews",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("supplier_id", sa.BigInteger(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("effective_date", sa.DateTime(timezone=True)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="ZAR"),
        sa.Column("price_basis", sa.String(16), nullable=False, server_default="tax_exclusive"),
        sa.Column("created_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_price_reviews_org", "price_reviews", ["organisation_id"])
    op.create_index("ix_price_reviews_supplier", "price_reviews", ["supplier_id"])

    op.create_table(
        "price_review_files",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("price_review_id", sa.BigInteger(), sa.ForeignKey("price_reviews.id"), nullable=False),
        sa.Column("file_type", sa.String(16), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer()),
        sa.Column("processing_status", sa.String(32), nullable=False, server_default="uploaded"),
        sa.Column("uploaded_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # spec Section 2 "prevent accidental duplicate processing" + Section 93 idempotency -
        # made structurally impossible rather than merely checked in application code.
        sa.UniqueConstraint("price_review_id", "checksum", name="uq_price_review_file_checksum"),
    )
    op.create_index("ix_price_review_files_org", "price_review_files", ["organisation_id"])

    op.create_table(
        "price_review_mapping_templates",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("supplier_id", sa.BigInteger(), sa.ForeignKey("suppliers.id")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("column_mapping", postgresql.JSONB(), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_mapping_templates_org", "price_review_mapping_templates", ["organisation_id"])

    op.create_table(
        "price_review_lines",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("price_review_id", sa.BigInteger(), sa.ForeignKey("price_reviews.id"), nullable=False),
        sa.Column("old_supplier_sku", sa.String(128)),
        sa.Column("old_description", sa.String(512)),
        sa.Column("old_pack_raw", sa.String(128)),
        sa.Column("old_price", sa.Numeric(18, 4)),
        sa.Column("old_normalized_price", sa.Numeric(18, 4)),
        sa.Column("old_normalized_base_unit", sa.String(8)),
        sa.Column("old_source_row_ref", postgresql.JSONB()),
        sa.Column("new_supplier_sku", sa.String(128)),
        sa.Column("new_description", sa.String(512)),
        sa.Column("new_pack_raw", sa.String(128)),
        sa.Column("new_price", sa.Numeric(18, 4)),
        sa.Column("new_normalized_price", sa.Numeric(18, 4)),
        sa.Column("new_normalized_base_unit", sa.String(8)),
        sa.Column("new_source_row_ref", postgresql.JSONB()),
        sa.Column("match_status", sa.String(32), nullable=False),
        sa.Column("match_method", sa.String(32)),
        sa.Column("match_confidence", sa.Numeric(5, 4)),
        sa.Column("match_confirmed_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("match_confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("movement_type", sa.String(32)),
        sa.Column("absolute_change", sa.Numeric(18, 4)),
        sa.Column("percentage_change", sa.Numeric(9, 6)),
        sa.Column("pack_changed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("risk_classification", sa.String(16)),
        sa.Column("historical_quantity", sa.Numeric(18, 4)),
        sa.Column("annual_quantity", sa.Numeric(18, 4)),
        sa.Column("quantity_source", sa.String(32)),
        sa.Column("quantity_confidence", sa.String(16)),
        sa.Column("historical_spend", sa.Numeric(18, 4)),
        sa.Column("annual_impact", sa.Numeric(18, 4)),
        sa.Column("selling_price", sa.Numeric(18, 4)),
        sa.Column("old_margin_pct", sa.Numeric(9, 6)),
        sa.Column("new_margin_pct", sa.Numeric(9, 6)),
        sa.Column("margin_movement_pct", sa.Numeric(9, 6)),
        sa.Column("annual_margin_impact", sa.Numeric(18, 4)),
        sa.Column("buyer_decision", sa.String(16)),
        sa.Column("buyer_decision_notes", sa.String(2048)),
        sa.Column("buyer_decision_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("buyer_decision_at", sa.DateTime(timezone=True)),
        sa.Column("target_price", sa.Numeric(18, 4)),
        sa.Column("potential_cost_avoidance", sa.Numeric(18, 4)),
        sa.Column("final_negotiated_price", sa.Numeric(18, 4)),
        sa.Column("actual_cost_avoidance", sa.Numeric(18, 4)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_price_review_lines_org", "price_review_lines", ["organisation_id"])
    op.create_index("ix_price_review_lines_review", "price_review_lines", ["price_review_id"])
    op.create_index("ix_price_review_lines_decision", "price_review_lines", ["buyer_decision"])

    op.create_table(
        "opportunities",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("opportunity_type", sa.String(32), nullable=False, server_default="price_increase_challenge"),
        sa.Column("supplier_id", sa.BigInteger(), sa.ForeignKey("suppliers.id")),
        sa.Column("price_review_id", sa.BigInteger(), sa.ForeignKey("price_reviews.id")),
        sa.Column("price_review_line_id", sa.BigInteger(), sa.ForeignKey("price_review_lines.id")),
        sa.Column("description", sa.String(2048)),
        sa.Column("requested_increase_pct", sa.Numeric(9, 6)),
        sa.Column("annual_financial_impact", sa.Numeric(18, 4)),
        sa.Column("negotiation_target_price", sa.Numeric(18, 4)),
        sa.Column("potential_cost_avoidance", sa.Numeric(18, 4)),
        sa.Column("owner_user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("status", sa.String(32), nullable=False, server_default="identified"),
        sa.Column("created_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_opportunities_org", "opportunities", ["organisation_id"])

    # --- ADR-003: RLS on every tenant-scoped table added in this migration, same pattern as 0001.
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
    op.drop_table("opportunities")
    op.drop_table("price_review_lines")
    op.drop_table("price_review_mapping_templates")
    op.drop_table("price_review_files")
    op.drop_table("price_reviews")
    op.drop_table("suppliers")
