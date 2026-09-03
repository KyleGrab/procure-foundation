from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class PurchaseInvoice(Base, TenantScopedMixin):
    """
    Append-only (ADR-006) - a posted invoice is a financial fact, never edited. A wrong invoice
    is corrected by a new invoice referencing corrects_id (credit-note-and-rebill, matching real
    accounting practice), never by mutating the original row. Correction happens at the header
    level, not per-line - a whole wrong invoice gets reversed, not individual lines within it.
    """

    __tablename__ = "purchase_invoices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    purchase_order_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"))

    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ZAR")

    corrects_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_invoices.id"))
    source_file_storage_key: Mapped[str | None] = mapped_column(String(512))
    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class PurchaseInvoiceLine(Base, TenantScopedMixin):
    """Append-only alongside its parent invoice - see PurchaseInvoice's docstring. net_amount is
    stored, not just derivable, so a historical line's figure never depends on re-running a
    calculation with today's rounding rules against it (spec Section 105's explainability
    principle: the number that was actually used is what's stored)."""

    __tablename__ = "purchase_invoice_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    purchase_invoice_id: Mapped[int] = mapped_column(ForeignKey("purchase_invoices.id"), nullable=False)
    purchase_order_line_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_order_lines.id"))

    supplier_sku: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(512))
    quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    discount_pct: Mapped[float | None] = mapped_column(Numeric(9, 6))
    tax_pct: Mapped[float | None] = mapped_column(Numeric(9, 6))
    net_amount: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
