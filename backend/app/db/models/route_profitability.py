from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class RouteProfitabilitySnapshot(Base, TenantScopedMixin):
    """
    Append-only (ADR-006) - a computed trip-level profitability fact, same category as
    CostToServeLedger. Stores the real inputs (revenue, cogs, the three granular cost pools) AND
    the computed net_net_profit - "the number that was actually used is what's stored" (same
    principle as PurchaseInvoiceLine.net_amount), not recomputed on every read from a formula
    that could drift.

    customer_id is Mapped[str | None] = String(128), NOT a foreign key - no customers table
    exists in this schema (confirmed before this model was written), matching
    CostToServeLedger.customer_id's exact, already-established precedent. location_id is a real
    integer FK to locations.id (this schema's standard internal-relationship convention) -
    never a UUID; UUIDs are reserved for public API-facing contracts only (public_id below).
    """

    __tablename__ = "route_profitability_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )

    trip_date: Mapped[date] = mapped_column(Date, nullable=False)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    customer_id: Mapped[str | None] = mapped_column(String(128))
    vehicle_registration: Mapped[str | None] = mapped_column(String(32))
    route_reference: Mapped[str | None] = mapped_column(String(64))

    revenue: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    cogs: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    trade_spend: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    revenue_basis: Mapped[str] = mapped_column(String(16), nullable=False)

    trip_fixed_costs: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    distance_variable_costs: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    activity_time_costs: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)

    net_net_profit: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    is_net_revenue_negative: Mapped[bool] = mapped_column(Boolean, nullable=False)

    corrects_id: Mapped[int | None] = mapped_column(ForeignKey("route_profitability_snapshots.id"))
    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
