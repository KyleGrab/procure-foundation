"""
Savings register routes (Phase 5). A reporting view over `opportunities` (the same table
`/opportunities` manages), not a separate table - matching migration 0009's choice to extend
`opportunities` with the five-type fields rather than create a parallel `savings` table.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.savings_register import calculate_savings_waterfall
from app.core.constants import Permission
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims
from app.db.models import Opportunity, Supplier
from app.db.session import get_db
from app.schemas.opportunity import OpportunityRead
from app.services import opportunity_service

router = APIRouter(prefix="/savings-register", tags=["savings-register"])


async def _resolve_supplier_public_ids(db: AsyncSession, opportunities: list[Opportunity]) -> dict[int, uuid.UUID]:
    """SAVINGS-REGISTER-READ-R1: local to this route (deliberately not imported from
    app/api/v1/opportunities.py - each route stays independent, matching docs/architecture.md's
    one-router-per-file convention), but mirrors the same reasoning as that route's own
    _resolve_supplier_public_id: Opportunity.supplier_id is a plain, nullable FK column with no
    ORM relationship (this codebase never uses SQLAlchemy relationship() anywhere), so the
    related supplier's public_id is always resolved with its own explicit, RLS-scoped query -
    batched once for every distinct supplier_id in this page rather than one query per row, same
    as opportunities.py's own list endpoint."""
    supplier_ids = {o.supplier_id for o in opportunities if o.supplier_id is not None}
    if not supplier_ids:
        return {}
    result = await db.execute(select(Supplier.id, Supplier.public_id).where(Supplier.id.in_(supplier_ids)))
    return dict(result.all())


def _to_read_model(opportunity: Opportunity, supplier_public_id: uuid.UUID | None) -> OpportunityRead:
    """Explicit construction - never OpportunityRead.model_validate(opportunity) - because
    opportunity.supplier_public_id doesn't exist as an attribute at all (see
    _resolve_supplier_public_ids above); a bare model_validate call fails with 'Field required'
    before ever reaching a null-vs-missing distinction. supplier_public_id is None when
    opportunity.supplier_id is None (a supplier is genuinely optional for an Opportunity) - never
    an invented/internal id. Every other field is read straight off the ORM instance, unchanged -
    no savings/waterfall value is recalculated, rounded, or overwritten here."""
    return OpportunityRead(
        public_id=opportunity.public_id, title=opportunity.title, opportunity_type=opportunity.opportunity_type,
        supplier_public_id=supplier_public_id, description=opportunity.description,
        annual_financial_impact=opportunity.annual_financial_impact,
        annual_financial_impact_status=opportunity.annual_financial_impact_status,
        annual_financial_impact_source_basis=opportunity.annual_financial_impact_source_basis,
        annual_financial_impact_effective_from=opportunity.annual_financial_impact_effective_from,
        savings_type=opportunity.savings_type, baseline_value=opportunity.baseline_value,
        baseline_methodology=opportunity.baseline_methodology, confidence=opportunity.confidence,
        realised_savings=opportunity.realised_savings, realised_savings_status=opportunity.realised_savings_status,
        realised_savings_source_basis=opportunity.realised_savings_source_basis,
        realised_savings_effective_period_start=opportunity.realised_savings_effective_period_start,
        realised_savings_effective_period_end=opportunity.realised_savings_effective_period_end,
        status=opportunity.status, approved_at=opportunity.approved_at,
        algorithm_version=opportunity.algorithm_version, calculation_timestamp=opportunity.calculation_timestamp,
    )


@router.get("", response_model=list[OpportunityRead])
async def list_savings_register(
    savings_type: str | None = None,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> list[OpportunityRead]:
    opportunities = await opportunity_service.list_opportunities(
        db, organisation_id=claims.active_org_id, savings_type=savings_type
    )
    supplier_public_ids = await _resolve_supplier_public_ids(db, opportunities)
    return [_to_read_model(o, supplier_public_ids.get(o.supplier_id)) for o in opportunities]


@router.get("/waterfall")
async def get_savings_waterfall(
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """spec Section 85: value AT each stage, never a blended running total - see
    app.analytics.savings_register.calculate_savings_waterfall's docstring.

    P-03: two real bugs fixed here, not just the false-zero collapse. First, `or 0` meant an
    unestimated opportunity silently contributed $0 to its stage rather than being excluded -
    now excluded entirely, and counted separately so the response shows what's missing, not just
    a total that looks complete. Second - a real, separate bug - every stage previously read
    annual_financial_impact, including 'realised' opportunities, which is exactly the annual-
    impact/realised-savings conflation this whole design exists to prevent. A realised
    opportunity now reads realised_savings, never annual_financial_impact.
    """
    opportunities = await opportunity_service.list_opportunities(db, organisation_id=claims.active_org_id)

    tuples: list[tuple[str, Decimal, bool]] = []
    excluded_unknown = 0
    excluded_legacy_unverified = 0

    for o in opportunities:
        if o.status == "realised":
            if o.realised_savings_status not in ("calculated", "confirmed"):
                if o.realised_savings_status == "legacy_unverified":
                    excluded_legacy_unverified += 1
                else:
                    excluded_unknown += 1
                continue
            amount = Decimal(str(o.realised_savings))
        else:
            if o.annual_financial_impact_status not in ("estimated", "calculated"):
                if o.annual_financial_impact_status == "legacy_unverified":
                    excluded_legacy_unverified += 1
                else:
                    excluded_unknown += 1
                continue
            amount = Decimal(str(o.annual_financial_impact))
        tuples.append((o.status, amount, o.savings_type == "working_capital"))

    totals = calculate_savings_waterfall(tuples)
    return {
        "identified": str(totals.identified), "validated": str(totals.validated),
        "approved": str(totals.approved), "implementation": str(totals.implementation),
        "realised": str(totals.realised),
        "excluded_count": excluded_unknown + excluded_legacy_unverified,
        "excluded_reason_breakdown": {"unknown": excluded_unknown, "legacy_unverified": excluded_legacy_unverified},
    }
