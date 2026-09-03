"""Executive summary metrics for the interactive card (dashboard home). Three counts, all real,
all scoped by RLS via get_db - no mocked/fabricated fields. No 'risk score' here: nothing in this
codebase computes supplier risk as a concept, so it isn't pretended into existence for a UI slot."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.contract_calculations import ContractStatus
from app.core.constants import Permission
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims
from app.db.models import Contract, RebatePeriodActual, RebateAgreement, SupplierConsolidationFlag
from app.db.session import get_db

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/executive-metrics")
async def get_executive_metrics(
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    active_contracts = await db.execute(
        select(func.count()).select_from(Contract)
        .where(Contract.organisation_id == claims.active_org_id)
        .where(Contract.status != ContractStatus.EXPIRED.value)
    )
    open_rebate_periods = await db.execute(
        select(func.count()).select_from(RebatePeriodActual)
        .join(RebateAgreement, RebateAgreement.id == RebatePeriodActual.rebate_agreement_id)
        .where(RebateAgreement.organisation_id == claims.active_org_id)
        .where(RebatePeriodActual.earned_amount.is_(None))
    )
    open_consolidation_flags = await db.execute(
        select(func.count()).select_from(SupplierConsolidationFlag)
        .where(SupplierConsolidationFlag.organisation_id == claims.active_org_id)
        .where(SupplierConsolidationFlag.status.in_(("flagged", "under_review")))
    )

    return {
        "active_contracts": active_contracts.scalar_one(),
        "open_rebate_periods": open_rebate_periods.scalar_one(),
        "open_consolidation_flags": open_consolidation_flags.scalar_one(),
    }
