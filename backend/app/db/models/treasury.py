from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class FXTransactionSnapshot(Base, TenantScopedMixin):
    """
    Append-only (ADR-006) - a computed FX exposure fact, same category as
    RouteProfitabilitySnapshot/CostToServeLedger: "the number that was actually used is what's
    stored," not recomputed from a formula that could drift.

    customer_id is Mapped[str | None] = String(128), NOT a foreign key - no customers table
    exists in this schema, matching CostToServeLedger's established precedent. supplier_id is a
    real integer FK (this schema's standard internal-relationship convention) - never a UUID.

    Structurally enforces the same mutual exclusivity as calculate_fx_transaction_exposure
    itself: hedging_gain_loss and unrealized_variance are both nullable, and a row has exactly
    one of the two populated, never both (fec_contract_rate IS NULL implies unrealized_variance
    IS NOT NULL and vice versa) - a CHECK constraint mirrors this at the DB level, not just in
    the pure function that computed the row.
    """

    __tablename__ = "fx_transaction_snapshots"
    __table_args__ = (
        CheckConstraint(
            "(is_hedged = true AND hedging_gain_loss IS NOT NULL AND unrealized_variance IS NULL) OR "
            "(is_hedged = false AND unrealized_variance IS NOT NULL AND hedging_gain_loss IS NULL)",
            name="ck_fx_transaction_snapshots_mutually_exclusive_variance",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )

    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    reporting_date: Mapped[date] = mapped_column(Date, nullable=False)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    customer_id: Mapped[str | None] = mapped_column(String(128))
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)

    foreign_currency_amount: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    transaction_date_spot_rate: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    reporting_date_spot_rate: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    fec_contract_rate: Mapped[float | None] = mapped_column(Numeric(12, 6))

    is_hedged: Mapped[bool] = mapped_column(Boolean, nullable=False)
    unrealized_variance: Mapped[float | None] = mapped_column(Numeric(18, 4))
    hedging_gain_loss: Mapped[float | None] = mapped_column(Numeric(18, 4))

    corrects_id: Mapped[int | None] = mapped_column(ForeignKey("fx_transaction_snapshots.id"))
    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
