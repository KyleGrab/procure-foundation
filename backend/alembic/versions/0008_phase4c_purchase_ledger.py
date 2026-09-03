"""Phase 4c: purchase_orders/purchase_order_lines (mutable, status workflow), purchase_invoices/
purchase_invoice_lines (append-only, ADR-006), goods_receipts/goods_receipt_lines (append-only).
RLS ENABLE+FORCE+grants applied from creation (ADR-011), append-only tables get SELECT+INSERT
only for procureiq_app, matching audit_logs/purchase_transactions' precedent.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_MUTABLE_TABLES = ("purchase_orders", "purchase_order_lines")
_APPEND_ONLY_TABLES = (
    "purchase_invoices", "purchase_invoice_lines", "goods_receipts", "goods_receipt_lines",
)


def upgrade() -> None:
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("supplier_id", sa.BigInteger(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("location_id", sa.BigInteger(), sa.ForeignKey("locations.id")),
        sa.Column("po_number", sa.String(64), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("expected_delivery_date", sa.Date()),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="ZAR"),
        sa.Column("created_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organisation_id", "po_number", name="uq_purchase_order_number"),
    )
    op.create_index("ix_purchase_orders_org", "purchase_orders", ["organisation_id"])
    op.create_index("ix_purchase_orders_supplier", "purchase_orders", ["supplier_id"])
    op.create_index("ix_purchase_orders_status", "purchase_orders", ["status"])

    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("purchase_order_id", sa.BigInteger(), sa.ForeignKey("purchase_orders.id"), nullable=False),
        sa.Column("supplier_sku", sa.String(128)),
        sa.Column("description", sa.String(512)),
        sa.Column("quantity_ordered", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("vat_rate_pct", sa.Numeric(9, 6)),
        sa.Column("line_total", sa.Numeric(18, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_purchase_order_lines_org", "purchase_order_lines", ["organisation_id"])
    op.create_index("ix_purchase_order_lines_po", "purchase_order_lines", ["purchase_order_id"])

    op.create_table(
        "purchase_invoices",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("supplier_id", sa.BigInteger(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("purchase_order_id", sa.BigInteger(), sa.ForeignKey("purchase_orders.id")),
        sa.Column("invoice_number", sa.String(64), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="ZAR"),
        sa.Column("corrects_id", sa.BigInteger(), sa.ForeignKey("purchase_invoices.id")),
        sa.Column("source_file_storage_key", sa.String(512)),
        sa.Column("uploaded_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_purchase_invoices_org", "purchase_invoices", ["organisation_id"])
    op.create_index("ix_purchase_invoices_supplier", "purchase_invoices", ["supplier_id"])
    op.create_index("ix_purchase_invoices_date", "purchase_invoices", ["invoice_date"])

    op.create_table(
        "purchase_invoice_lines",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("purchase_invoice_id", sa.BigInteger(), sa.ForeignKey("purchase_invoices.id"), nullable=False),
        sa.Column("purchase_order_line_id", sa.BigInteger(), sa.ForeignKey("purchase_order_lines.id")),
        sa.Column("supplier_sku", sa.String(128)),
        sa.Column("description", sa.String(512)),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("discount_pct", sa.Numeric(9, 6)),
        sa.Column("tax_pct", sa.Numeric(9, 6)),
        sa.Column("net_amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_purchase_invoice_lines_org", "purchase_invoice_lines", ["organisation_id"])
    op.create_index("ix_purchase_invoice_lines_invoice", "purchase_invoice_lines", ["purchase_invoice_id"])

    op.create_table(
        "goods_receipts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("supplier_id", sa.BigInteger(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("purchase_order_id", sa.BigInteger(), sa.ForeignKey("purchase_orders.id")),
        sa.Column("location_id", sa.BigInteger(), sa.ForeignKey("locations.id")),
        sa.Column("receipt_number", sa.String(64)),
        sa.Column("receipt_date", sa.Date(), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_goods_receipts_org", "goods_receipts", ["organisation_id"])
    op.create_index("ix_goods_receipts_po", "goods_receipts", ["purchase_order_id"])

    op.create_table(
        "goods_receipt_lines",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("organisation_id", sa.BigInteger(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("goods_receipt_id", sa.BigInteger(), sa.ForeignKey("goods_receipts.id"), nullable=False),
        sa.Column("purchase_order_line_id", sa.BigInteger(), sa.ForeignKey("purchase_order_lines.id")),
        sa.Column("supplier_sku", sa.String(128)),
        sa.Column("description", sa.String(512)),
        sa.Column("quantity_ordered", sa.Numeric(18, 4)),
        sa.Column("quantity_received", sa.Numeric(18, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_goods_receipt_lines_org", "goods_receipt_lines", ["organisation_id"])
    op.create_index("ix_goods_receipt_lines_receipt", "goods_receipt_lines", ["goods_receipt_id"])

    all_tables = _MUTABLE_TABLES + _APPEND_ONLY_TABLES
    for table in all_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (organisation_id = current_setting('app.current_org_id', true)::bigint)
            """
        )

    for table in _MUTABLE_TABLES:
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
    for table in _APPEND_ONLY_TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procureiq_app') THEN
                    -- No UPDATE/DELETE - a financial fact or receipt event is corrected by a new
                    -- row, never mutated (ADR-006), same as purchase_transactions/audit_logs.
                    GRANT SELECT, INSERT ON {table} TO procureiq_app;
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
    all_tables = _MUTABLE_TABLES + _APPEND_ONLY_TABLES
    for table in reversed(all_tables):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("goods_receipt_lines")
    op.drop_table("goods_receipts")
    op.drop_table("purchase_invoice_lines")
    op.drop_table("purchase_invoices")
    op.drop_table("purchase_order_lines")
    op.drop_table("purchase_orders")
