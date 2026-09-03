from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class InventorySnapshot(Base, TenantScopedMixin):
    """
    Phase 5b (ADR-018). Append-only (ADR-006, same as purchase_transactions/purchase_invoices/
    goods_receipts) - a stocktake snapshot is a fact-in-time ("this was the count on this date"),
    not an in-progress document; a bad count is corrected via a new row referencing corrects_id,
    never a silent UPDATE. Grain: (description, supplier_sku, location_id, snapshot_date) - one
    row per item per location per day, matching the free-text-item-identity convention every
    other purchase-adjacent table in this codebase already uses (no `products` table exists -
    deliberate since Phase 2, restated in ADR-015/ADR-018). No DB-level UNIQUE constraint on the
    grain: a rigid constraint would reject messy real-world uploads outright; the pure
    app.analytics.inventory_calculations.validate_snapshot_grain check flags violations explicitly
    for the ingestion layer to surface, rather than the DB silently rejecting or silently allowing
    a duplicate.

    reorder_level/unit_cost/expiry_date are all nullable, on purpose - calculate_excess_stock_value
    and classify_expiry_risk both return None/no_expiry_tracked rather than a fabricated figure
    when these are absent, so there's no reason to force a value into the schema that the org's
    real data doesn't have.
    """

    __tablename__ = "inventory_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)

    supplier_sku: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)

    quantity_on_hand: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[float | None] = mapped_column(Numeric(18, 4))
    reorder_level: Mapped[float | None] = mapped_column(Numeric(18, 4))
    expiry_date: Mapped[date | None] = mapped_column(Date)

    corrects_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_snapshots.id"))
    source_file_storage_key: Mapped[str | None] = mapped_column(String(512))
    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
