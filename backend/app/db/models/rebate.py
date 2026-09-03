from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.analytics.rebate_calculations import EntrySource
from app.db.base import Base, TenantScopedMixin


class RebateAgreement(Base, TenantScopedMixin):
    """
    Structured, calculable rebate terms - deliberately separate from Contract.rebate_terms_summary
    (a human-verified free-text summary, never an input to a formula - see
    docs/phase4-rebate-leakage-plan.md §2). `bands` mirrors ContractCalculations' RebateBand shape
    as JSONB: [{"threshold_spend": "1000000", "rate_pct": "0.025"}, ...].

    Widened (Phase 2, sell-side trade spend) to represent both directions: buy-side (rebates
    earned FROM a supplier, supplier_id set) and sell-side (trade spend paid TO a customer,
    customer_id set). Real, quantified reason: TTM Rebates Paid (R3,145,913.07) is over 3x TTM
    Rebates Received (R976,235.71) in this engagement's real data, and only the smaller,
    buy-side direction had a home anywhere in this schema before this change.

    customer_id is Mapped[str | None], not a foreign key - no customers table exists in this
    schema (confirmed before this change, not assumed), and CostToServeLedger.customer_id
    already establishes this exact free-text precedent for the identical real-world concept
    (a retail customer identifier with no internal master-data table backing it yet). Inventing
    a new customers table as a side effect of this migration would be unplanned scope, not what
    was asked - matching this whole engagement's discipline about not silently building beyond
    what's warranted.

    calculate_rebate_leakage/calculate_aggregate_rebate_leakage needed zero code changes for
    this widening - they were already generic over (expected, received) Decimal pairs with no
    supplier/customer concept baked in (see tests_pure/test_rebate_calculations.py's
    test_function_is_already_direction_agnostic...). `direction` here is the one thing that
    genuinely needed to exist: which side of the relationship this specific row represents.
    """

    __tablename__ = "rebate_agreements"
    __table_args__ = (
        CheckConstraint(
            "supplier_id IS NOT NULL OR customer_id IS NOT NULL",
            name="ck_rebate_agreements_supplier_or_customer",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    customer_id: Mapped[str | None] = mapped_column(String(128))
    # 'buy_side' | 'sell_side' - explicit, not inferred from which of supplier_id/customer_id is
    # set. A future third direction (e.g. an intercompany rebate) would otherwise have nowhere
    # to declare itself without this being its own field.
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="buy_side")
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contracts.id"))

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    rebate_type: Mapped[str] = mapped_column(String(32), nullable=False)  # RebateType values
    period_type: Mapped[str] = mapped_column(String(16), nullable=False, default="quarterly")

    flat_rate_pct: Mapped[float | None] = mapped_column(Numeric(9, 6))
    bands: Mapped[list | None] = mapped_column(JSONB)
    fixed_amount: Mapped[float | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ZAR")

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class RebatePeriodActual(Base, TenantScopedMixin):
    """
    One row per rebate period (spec Section 29's expected/earned/received tracking). Carries both
    possible provenances from the start (ADR-013) - entry_source distinguishes a manual figure
    (ADR-012, Phase 4a) from one aggregated out of real purchase_transactions (Phase 4b) without
    the schema changing shape when 4b lands.

    P-03: expected_amount_status et al. are the CURRENT-STATE snapshot of the evidence tier for
    expected_amount - a DERIVED view of financial_amount_status_events, proven so by a deferred
    constraint trigger (migration 0021), not just a service-layer convention. period_start/
    period_end above already define this measure's effective period authoritatively - no
    separate period field needed here, unlike the two Opportunity measures.

    expected_amount_current_event_id is nullable at the schema level deliberately - a new row
    and its genesis event have a circular dependency (the event needs this row's id; this row's
    pointer needs the event's id), resolved by inserting this row with a NULL pointer, then the
    genesis event, then updating the pointer - all in one transaction, checked only at COMMIT.
    """

    __tablename__ = "rebate_period_actuals"
    __table_args__ = (
        CheckConstraint(
            "expected_amount_status IN "
            "('unknown','not_applicable','legacy_unverified','estimated','calculated','confirmed')",
            name="ck_rpa_expected_amount_status_valid",
        ),
        CheckConstraint(
            "expected_amount_source_basis IS NULL OR expected_amount_source_basis IN "
            "('manual_estimate','contract_terms_calculation','supplier_statement','credit_note')",
            name="ck_rpa_expected_amount_source_basis_vocabulary",
        ),
        CheckConstraint(
            "(expected_amount_status IN ('unknown','not_applicable') AND expected_amount IS NULL "
            "  AND expected_amount_source_basis IS NULL AND expected_amount_calculated_at IS NULL "
            "  AND expected_amount_approved_at IS NULL AND expected_amount_approved_by_user_id IS NULL)"
            " OR (expected_amount_status = 'legacy_unverified' AND expected_amount IS NOT NULL "
            "  AND expected_amount_source_basis IS NULL AND expected_amount_calculated_at IS NULL "
            "  AND expected_amount_approved_at IS NULL AND expected_amount_approved_by_user_id IS NULL)"
            " OR (expected_amount_status = 'estimated' AND expected_amount IS NOT NULL "
            "  AND expected_amount_source_basis IS NOT NULL AND expected_amount_source_basis = 'manual_estimate' "
            "  AND expected_amount_calculated_at IS NULL "
            "  AND expected_amount_approved_at IS NULL AND expected_amount_approved_by_user_id IS NULL)"
            " OR (expected_amount_status = 'calculated' AND expected_amount IS NOT NULL "
            "  AND expected_amount_source_basis IS NOT NULL "
            "  AND expected_amount_source_basis = 'contract_terms_calculation' "
            "  AND expected_amount_calculated_at IS NOT NULL "
            "  AND expected_amount_approved_at IS NULL AND expected_amount_approved_by_user_id IS NULL)"
            " OR (expected_amount_status = 'confirmed' AND expected_amount IS NOT NULL "
            "  AND expected_amount_source_basis IS NOT NULL "
            "  AND expected_amount_source_basis IN ('supplier_statement','credit_note') "
            "  AND expected_amount_calculated_at IS NULL "
            "  AND expected_amount_approved_at IS NOT NULL AND expected_amount_approved_by_user_id IS NOT NULL)",
            name="ck_rpa_expected_amount_state_combination",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    rebate_agreement_id: Mapped[int] = mapped_column(ForeignKey("rebate_agreements.id"), nullable=False)

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    actual_spend: Mapped[float | None] = mapped_column(Numeric(18, 4))
    actual_volume: Mapped[float | None] = mapped_column(Numeric(18, 4))
    entry_source: Mapped[str] = mapped_column(String(32), nullable=False, default=EntrySource.MANUAL.value)
    # 'manual' (ADR-012/4a) | 'transaction_aggregation' (4b)

    expected_amount: Mapped[float | None] = mapped_column(Numeric(18, 4))
    expected_amount_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    expected_amount_source_basis: Mapped[str | None] = mapped_column(String(64))
    expected_amount_calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_amount_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_amount_approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    expected_amount_current_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_amount_status_events.id")
    )
    earned_amount: Mapped[float | None] = mapped_column(Numeric(18, 4))
    earned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_amount: Mapped[float | None] = mapped_column(Numeric(18, 4))
    received_reference: Mapped[str | None] = mapped_column(String(128))  # credit note / payment ref

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="on_track")
    status_calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    entered_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class RebateAlert(Base, TenantScopedMixin):
    """Idempotency record mirroring ContractAlert's pattern exactly (spec Section 29's
    "approaching threshold" alerts) - see app.analytics.rebate_calculations.is_threshold_alert_due."""

    __tablename__ = "rebate_alerts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rebate_period_actual_id: Mapped[int] = mapped_column(
        ForeignKey("rebate_period_actuals.id"), nullable=False
    )

    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 'threshold_approaching' etc.
    trigger_date: Mapped[date] = mapped_column(Date, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
