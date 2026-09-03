from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class GoodsReceipt(Base, TenantScopedMixin):
    """Append-only - a receipt event, like an invoice, is something that happened and is recorded,
    not a document that gets edited (ADR-006's philosophy applied to receiving, not just billing).
    purchase_order_id is nullable to allow ad-hoc receipts not tied to a formal PO, though the
    common case links back to one for ordered-vs-delivered reconciliation."""

    __tablename__ = "goods_receipts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    purchase_order_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))

    receipt_number: Mapped[str | None] = mapped_column(String(64))
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)

    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class GoodsReceiptLine(Base, TenantScopedMixin):
    __tablename__ = "goods_receipt_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    goods_receipt_id: Mapped[int] = mapped_column(ForeignKey("goods_receipts.id"), nullable=False)
    purchase_order_line_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_order_lines.id"))

    supplier_sku: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(512))
    # quantity_ordered is copied here (not just joined via purchase_order_line_id) so a receipt's
    # variance is explainable (spec Section 105) even if the PO line is later changed - the
    # figure a receipt was actually reconciled against at the time is what's stored.
    quantity_ordered: Mapped[float | None] = mapped_column(Numeric(18, 4))
    quantity_received: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
