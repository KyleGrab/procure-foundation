from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class InventoryReconciliation(Base, TenantScopedMixin):
    """
    Gate A: persists what check_inventory_reconciliation/resolve_gated_inventory_value already
    compute (app/analytics/management_accounting.py, real, tested since the Chaos Audit) - this
    table adds no new reconciliation logic of its own, only a durable record of a period's
    result. raw_subledger_total and bridge_total are NEVER seeded with fabricated data by this
    migration - both are genuinely nullable until a real sub-ledger extract is actually read
    (the source Inventory Valuation Report has been unreadable this entire engagement: no xlrd,
    no network). gl_control_total defaults to nothing invented either, but the one real, verified
    figure available (R21,895,070.82, confirmed against the actual Balance Sheet) is the only
    value in this whole schema that could legitimately be inserted as real data - and even that
    is a service-layer decision, not something this migration seeds.

    reconciled_total and final_variance are DB-enforced identities (CHECK constraints), not
    trusted input - mirrors calculate_true_route_profitability's own "reuse the tested formula,
    don't let a caller assert an inconsistent number" discipline, at the schema layer instead of
    the pure-function layer.
    """

    __tablename__ = "inventory_reconciliations"
    __table_args__ = (
        CheckConstraint("valuation_basis = 'moving_average_cost'", name="ck_inv_recon_valuation_basis"),
        CheckConstraint(
            "reconciled_total = raw_subledger_total + bridge_total", name="ck_inv_recon_reconciled_identity"
        ),
        CheckConstraint(
            "final_variance = reconciled_total - gl_control_total", name="ck_inv_recon_variance_identity"
        ),
        Index(
            "uq_inv_recon_root_per_org_date", "organisation_id", "snapshot_date",
            unique=True, postgresql_where="corrects_id IS NULL",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )

    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    valuation_basis: Mapped[str] = mapped_column(String(32), nullable=False, default="moving_average_cost")

    raw_subledger_total: Mapped[float | None] = mapped_column(Numeric(18, 4))
    gl_control_total: Mapped[float | None] = mapped_column(Numeric(18, 4))
    bridge_total: Mapped[float | None] = mapped_column(Numeric(18, 4))
    reconciled_total: Mapped[float | None] = mapped_column(Numeric(18, 4))
    final_variance: Mapped[float | None] = mapped_column(Numeric(18, 4))
    tolerance: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0.01)

    raw_detail_row_count: Mapped[int | None] = mapped_column(Integer)
    bridge_row_count: Mapped[int | None] = mapped_column(Integer)

    is_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    corrects_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_reconciliations.id"), unique=True)
    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class InventoryReconciliationBridge(Base, TenantScopedMixin):
    """
    A single unallocated timing-bridge line item. Deliberately has NO product/customer/location/
    warehouse/route column at all - not nullable dimensions, genuinely absent - matching
    refuse_timing_bridge_allocation's own principle (already built, already tested) that a
    reconciliation gap must be structurally impossible to allocate to any specific entity, held
    at the tenant/global ledger level only.
    """

    __tablename__ = "inventory_reconciliation_bridges"
    __table_args__ = (
        CheckConstraint(
            "reason_code = 'GL_SUBLEDGER_TIMING_VARIANCE'", name="ck_inv_recon_bridge_reason"
        ),
        CheckConstraint(
            "allocation_scope = 'organisation_unallocated'", name="ck_inv_recon_bridge_scope"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )

    reconciliation_id: Mapped[int] = mapped_column(ForeignKey("inventory_reconciliations.id"), nullable=False)
    reference_code: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False, default="GL_SUBLEDGER_TIMING_VARIANCE")
    allocation_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="organisation_unallocated")
    evidence_checksum: Mapped[str | None] = mapped_column(String(128))
    source_reference: Mapped[str | None] = mapped_column(String(255))
