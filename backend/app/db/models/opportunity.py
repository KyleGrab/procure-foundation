from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class Opportunity(Base, TenantScopedMixin):
    """
    Opportunity register (spec Section 25, extended in Phase 5 per spec Sections 9/34/35/105-106).
    Phase 2 built the minimal subset a price-review line needs; Phase 5 adds the fields that make
    this a real savings register: the five-type discipline (savings_type - never blended, see
    app.analytics.savings_register), the waterfall stages (status, now with a defined vocabulary),
    baseline/methodology/confidence for explainability, and algorithm_version/calculation_timestamp/
    source_dataset_ref so every figure traces back to how and when it was computed.

    P-03: annual_financial_impact and realised_savings each get their OWN full evidence-state
    (status/source_basis/calculated_at/current_event_id) - two independent measures, never
    sharing columns, so they can never be summed together by construction. Their vocabularies
    differ deliberately: annual_financial_impact (prospective, a forecast) can never reach
    'confirmed' - a confirmed amount requires evidence of an occurred result, which a forecast by
    definition doesn't have. realised_savings (retrospective, an occurred fact) can never reach
    'estimated' - a realised saving cannot itself be a forecast. Approval-workflow fields
    (approved_by_user_id/approved_at above) are a SEPARATE, pre-existing concept (opportunity
    workflow-stage approval) from realised_savings_approved_at (evidence-tier confirmation) -
    deliberately non-colliding names, not the same thing reused.
    """

    __tablename__ = "opportunities"
    __table_args__ = (
        CheckConstraint(
            "annual_financial_impact_status IN "
            "('unknown','not_applicable','legacy_unverified','estimated','calculated')",
            name="ck_opp_afi_status_valid",
        ),
        CheckConstraint(
            "annual_financial_impact_source_basis IS NULL OR annual_financial_impact_source_basis IN "
            "('manual_estimate','price_review_calculation')",
            name="ck_opp_afi_source_basis_vocabulary",
        ),
        CheckConstraint(
            "(annual_financial_impact_status IN ('unknown','not_applicable') AND annual_financial_impact IS NULL "
            "  AND annual_financial_impact_source_basis IS NULL AND annual_financial_impact_calculated_at IS NULL "
            "  AND annual_financial_impact_effective_from IS NULL)"
            " OR (annual_financial_impact_status = 'legacy_unverified' AND annual_financial_impact IS NOT NULL "
            "  AND annual_financial_impact_source_basis IS NULL AND annual_financial_impact_calculated_at IS NULL "
            "  AND annual_financial_impact_effective_from IS NULL)"
            " OR (annual_financial_impact_status = 'estimated' AND annual_financial_impact IS NOT NULL "
            "  AND annual_financial_impact_source_basis IS NOT NULL "
            "  AND annual_financial_impact_source_basis = 'manual_estimate' "
            "  AND annual_financial_impact_calculated_at IS NULL "
            "  AND annual_financial_impact_effective_from IS NOT NULL)"
            " OR (annual_financial_impact_status = 'calculated' AND annual_financial_impact IS NOT NULL "
            "  AND annual_financial_impact_source_basis IS NOT NULL "
            "  AND annual_financial_impact_source_basis = 'price_review_calculation' "
            "  AND annual_financial_impact_calculated_at IS NOT NULL "
            "  AND annual_financial_impact_effective_from IS NOT NULL)",
            name="ck_opp_afi_state_combination",
        ),
        CheckConstraint(
            "realised_savings_status IN "
            "('unknown','not_applicable','legacy_unverified','calculated','confirmed')",
            name="ck_opp_rs_status_valid",
        ),
        CheckConstraint(
            "realised_savings_source_basis IS NULL OR realised_savings_source_basis IN "
            "('actual_cost_data_calculation','reconciled_actuals')",
            name="ck_opp_rs_source_basis_vocabulary",
        ),
        CheckConstraint(
            "(realised_savings_status IN ('unknown','not_applicable') AND realised_savings IS NULL "
            "  AND realised_savings_source_basis IS NULL AND realised_savings_calculated_at IS NULL "
            "  AND realised_savings_approved_at IS NULL AND realised_savings_approved_by_user_id IS NULL "
            "  AND realised_savings_effective_period_start IS NULL AND realised_savings_effective_period_end IS NULL)"
            " OR (realised_savings_status = 'legacy_unverified' AND realised_savings IS NOT NULL "
            "  AND realised_savings_source_basis IS NULL AND realised_savings_calculated_at IS NULL "
            "  AND realised_savings_approved_at IS NULL AND realised_savings_approved_by_user_id IS NULL "
            "  AND realised_savings_effective_period_start IS NULL AND realised_savings_effective_period_end IS NULL)"
            " OR (realised_savings_status = 'calculated' AND realised_savings IS NOT NULL "
            "  AND realised_savings_source_basis IS NOT NULL "
            "  AND realised_savings_source_basis = 'actual_cost_data_calculation' "
            "  AND realised_savings_calculated_at IS NOT NULL "
            "  AND realised_savings_approved_at IS NULL AND realised_savings_approved_by_user_id IS NULL "
            "  AND realised_savings_effective_period_start IS NOT NULL AND realised_savings_effective_period_end IS NOT NULL "
            "  AND realised_savings_effective_period_start <= realised_savings_effective_period_end)"
            " OR (realised_savings_status = 'confirmed' AND realised_savings IS NOT NULL "
            "  AND realised_savings_source_basis IS NOT NULL AND realised_savings_source_basis = 'reconciled_actuals' "
            "  AND realised_savings_calculated_at IS NULL "
            "  AND realised_savings_approved_at IS NOT NULL AND realised_savings_approved_by_user_id IS NOT NULL "
            "  AND realised_savings_effective_period_start IS NOT NULL AND realised_savings_effective_period_end IS NOT NULL "
            "  AND realised_savings_effective_period_start <= realised_savings_effective_period_end)",
            name="ck_opp_rs_state_combination",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    opportunity_type: Mapped[str] = mapped_column(String(32), nullable=False, default="price_increase_challenge")
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    price_review_id: Mapped[int | None] = mapped_column(ForeignKey("price_reviews.id"))
    price_review_line_id: Mapped[int | None] = mapped_column(ForeignKey("price_review_lines.id"))

    description: Mapped[str | None] = mapped_column(String(2048))
    requested_increase_pct: Mapped[float | None] = mapped_column(Numeric(9, 6))
    annual_financial_impact: Mapped[float | None] = mapped_column(Numeric(18, 4))
    annual_financial_impact_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    annual_financial_impact_source_basis: Mapped[str | None] = mapped_column(String(64))
    annual_financial_impact_calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    annual_financial_impact_effective_from: Mapped[date | None] = mapped_column(Date)
    annual_financial_impact_current_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_amount_status_events.id")
    )
    negotiation_target_price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    potential_cost_avoidance: Mapped[float | None] = mapped_column(Numeric(18, 4))

    # --- Phase 5 additions: the five-type discipline as a real column, not an implied one ---
    savings_type: Mapped[str | None] = mapped_column(String(32))  # SavingsType values - see savings_register.py
    baseline_value: Mapped[float | None] = mapped_column(Numeric(18, 4))
    baseline_methodology: Mapped[str | None] = mapped_column(String(32))  # BaselineMethodology values
    confidence: Mapped[str | None] = mapped_column(String(16))  # 'low' | 'medium' | 'high'
    realised_savings: Mapped[float | None] = mapped_column(Numeric(18, 4))
    realised_savings_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    realised_savings_source_basis: Mapped[str | None] = mapped_column(String(64))
    realised_savings_calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    realised_savings_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    realised_savings_approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    realised_savings_effective_period_start: Mapped[date | None] = mapped_column(Date)
    realised_savings_effective_period_end: Mapped[date | None] = mapped_column(Date)
    realised_savings_current_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_amount_status_events.id")
    )
    # status (below) already carries the waterfall stage since Phase 2 - no separate
    # verification_status field. spec §35's stages become status's defined vocabulary:
    # 'identified'|'validated'|'approved'|'implementation'|'realised'|'rejected'|'expired'.
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- explainability (spec Section 105-106) ---
    algorithm_version: Mapped[str | None] = mapped_column(String(32))
    calculation_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_dataset_ref: Mapped[str | None] = mapped_column(String(255))

    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="identified")
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
