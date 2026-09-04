from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class PurchaseTransaction(Base, TenantScopedMixin):
    """
    Phase 4b: minimal append-only purchase fact (ADR-006's pattern - financial facts are never
    mutated). Deliberately NOT the full `purchase_invoices`/PO/GRN-reconciliation model from the
    original master spec (that's Phase 4c, explicitly deferred - see
    docs/decisions/ADR-013-phase4-three-tier-sequencing.md). Just enough fields to aggregate into
    a rebate period's actual spend/volume (app.analytics.rebate_calculations.
    aggregate_transactions_for_period) - not a general ledger, not linked to purchase orders or
    goods receipts, no line-level product matching against a product catalog (there isn't one -
    see docs/phase2-price-review-plan.md §2.3's reasoning for why price review didn't build one
    either).

    corrects_id follows the same append-only correction pattern as ADR-006: a wrong transaction
    is never UPDATEd or DELETEd, only superseded by a new row referencing it.
    """

    __tablename__ = "purchase_transactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)

    supplier_sku: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(512))
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    quantity: Mapped[float | None] = mapped_column(Numeric(18, 4))
    reference: Mapped[str | None] = mapped_column(String(128))

    corrects_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_transactions.id"))
    source_file_storage_key: Mapped[str | None] = mapped_column(String(512))
    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
