"""
Savings register routes (Phase 5). A reporting view over `opportunities` (the same table
`/opportunities` manages), not a separate table - matching migration 0009's choice to extend
`opportunities` with the five-type fields rather than create a parallel `savings` table.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.savings_register import calculate_savings_waterfall
from app.core.constants import Permission
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims
from app.db.session import get_db
from app.schemas.opportunity import OpportunityRead
from app.services import opportunity_service

router = APIRouter(prefix="/savings-register", tags=["savings-register"])


@router.get("", response_model=list[OpportunityRead])
async def list_savings_register(
    savings_type: str | None = None,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> list[OpportunityRead]:
    opportunities = await opportunity_service.list_opportunities(
        db, organisation_id=claims.active_org_id, savings_type=savings_type
    )
    return [OpportunityRead.model_validate(o) for o in opportunities]


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
