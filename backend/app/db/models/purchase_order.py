from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class PurchaseOrder(Base, TenantScopedMixin):
    """
    Mutable (status workflow: draft -> sent -> confirmed -> partially_received -> received ->
    cancelled) - unlike PurchaseInvoice/GoodsReceipt below, a PO genuinely does get updated as it
    progresses, so it's not append-only (ADR-006 applies to financial *facts* - things that
    happened - not to a document still being negotiated).
    """

    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))

    po_number: Mapped[str] = mapped_column(String(64), nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_delivery_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ZAR")

    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class PurchaseOrderLine(Base, TenantScopedMixin):
    __tablename__ = "purchase_order_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)

    supplier_sku: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(512))
    quantity_ordered: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    vat_rate_pct: Mapped[float | None] = mapped_column(Numeric(9, 6))
    line_total: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
