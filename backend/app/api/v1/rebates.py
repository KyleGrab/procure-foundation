"""Rebate API surface (spec Section 29, Phase 4a). Thin routes - logic in
services/rebate_service.py per docs/architecture.md's rule."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends

from app.core.constants import Permission
from app.core.exceptions import NotFoundError
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims
from app.db.models import RebateAgreement, RebatePeriodActual, Supplier
from app.db.session import get_db
from app.schemas.rebate import (
    RebateAgreementCreate,
    RebateAgreementRead,
    RebatePeriodActualCreate,
    RebatePeriodActualRead,
    RebateReceiptRecord,
    RebateReceiptRecordResponse,
)
from app.services import rebate_service

router = APIRouter(prefix="/rebates", tags=["rebates"])


async def _get_agreement(db: AsyncSession, public_id: str) -> RebateAgreement:
    result = await db.execute(select(RebateAgreement).where(RebateAgreement.public_id == public_id))
    agreement = result.scalar_one_or_none()
    if agreement is None:
        raise NotFoundError("Rebate agreement not found")
    return agreement


async def _resolve_supplier_public_id(db: AsyncSession, agreement: RebateAgreement) -> uuid.UUID:
    """See RebateAgreementRead's own docstring for the domain-gate decision this encodes: every
    RebateAgreement reachable through this API is buy-side today, so this raises loudly rather
    than returning None/a wrong value if that invariant is ever violated - a silent gap here
    would be worse than a clear 500 pointing straight at the cause."""
    if agreement.supplier_id is None:
        raise RuntimeError(
            f"RebateAgreement {agreement.id} has no supplier_id (a customer-side agreement) - "
            "this route does not support serializing customer-side rebate agreements yet"
        )
    result = await db.execute(select(Supplier.public_id).where(Supplier.id == agreement.supplier_id))
    return result.scalar_one()


def _to_read_model(agreement: RebateAgreement, supplier_public_id: uuid.UUID) -> RebateAgreementRead:
    return RebateAgreementRead(
        public_id=agreement.public_id, supplier_public_id=supplier_public_id, title=agreement.title,
        rebate_type=agreement.rebate_type, period_type=agreement.period_type,
        flat_rate_pct=agreement.flat_rate_pct, bands=agreement.bands, fixed_amount=agreement.fixed_amount,
        currency=agreement.currency, status=agreement.status,
    )


async def _get_period_actual(db: AsyncSession, agreement_id: int, public_id: str) -> RebatePeriodActual:
    result = await db.execute(
        select(RebatePeriodActual)
        .where(RebatePeriodActual.public_id == public_id)
        .where(RebatePeriodActual.rebate_agreement_id == agreement_id)
    )
    period_actual = result.scalar_one_or_none()
    if period_actual is None:
        raise NotFoundError("Rebate period not found")
    return period_actual


@router.post("", response_model=RebateAgreementRead, status_code=201)
async def create_rebate_agreement(
    payload: RebateAgreementCreate,
    claims: AccessTokenClaims = Depends(require_permission(Permission.EDIT_SUPPLIERS)),
    db: AsyncSession = Depends(get_db),
) -> RebateAgreementRead:
    agreement = await rebate_service.create_rebate_agreement(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, payload=payload
    )
    # payload.supplier_public_id was already validated (and, via RLS, confirmed to belong to this
    # org) by rebate_service.create_rebate_agreement before it set agreement.supplier_id from it -
    # safe to echo straight back, same pattern app/api/v1/purchase_orders.py's create route uses.
    return _to_read_model(agreement, payload.supplier_public_id)


@router.get("/{agreement_public_id}", response_model=RebateAgreementRead)
async def get_rebate_agreement(
    agreement_public_id: str,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> RebateAgreementRead:
    agreement = await _get_agreement(db, agreement_public_id)
    supplier_public_id = await _resolve_supplier_public_id(db, agreement)
    return _to_read_model(agreement, supplier_public_id)


@router.post("/{agreement_public_id}/periods", response_model=RebatePeriodActualRead, status_code=201)
async def record_rebate_period_actual(
    agreement_public_id: str, payload: RebatePeriodActualCreate,
    claims: AccessTokenClaims = Depends(require_permission(Permission.UPLOAD_DATA)),
    db: AsyncSession = Depends(get_db),
) -> RebatePeriodActualRead:
    """Phase 4a: manual entry (ADR-012) - entry_source is set server-side, never accepted from
    the client, so a caller cannot claim manually-typed figures came from real transactions."""
    agreement = await _get_agreement(db, agreement_public_id)
    period_actual = await rebate_service.record_period_actual(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id,
        agreement=agreement, payload=payload,
    )
    derived = rebate_service.get_derived_progress(agreement, period_actual)
    return RebatePeriodActualRead(**RebatePeriodActualRead.model_validate(period_actual).model_dump(exclude={"next_tier_threshold", "amount_to_next_tier"}), **derived)


@router.get("/{agreement_public_id}/periods/{period_public_id}", response_model=RebatePeriodActualRead)
async def get_rebate_period_actual(
    agreement_public_id: str, period_public_id: str,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> RebatePeriodActualRead:
    agreement = await _get_agreement(db, agreement_public_id)
    period_actual = await _get_period_actual(db, agreement.id, period_public_id)
    derived = rebate_service.get_derived_progress(agreement, period_actual)
    return RebatePeriodActualRead(**RebatePeriodActualRead.model_validate(period_actual).model_dump(exclude={"next_tier_threshold", "amount_to_next_tier"}), **derived)


@router.post("/{agreement_public_id}/periods/{period_public_id}/check-alerts")
async def check_rebate_threshold_alert(
    agreement_public_id: str, period_public_id: str,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manual trigger in this delivery - the confirmed 'dynamic recalculation on ingestion' +
    'monthly close' design means a scheduled job (Phase 9) is what should call this and
    close_period in production, same caveat as contracts' check-alerts endpoint."""
    agreement = await _get_agreement(db, agreement_public_id)
    period_actual = await _get_period_actual(db, agreement.id, period_public_id)
    alert = await rebate_service.check_threshold_alert(
        db, organisation_id=claims.active_org_id, agreement=agreement, period_actual=period_actual
    )
    return {"alert_fired": alert.alert_type if alert else None}


@router.post("/{agreement_public_id}/periods/{period_public_id}/close", response_model=RebatePeriodActualRead)
async def close_rebate_period(
    agreement_public_id: str, period_public_id: str,
    claims: AccessTokenClaims = Depends(require_permission(Permission.APPROVE_SAVINGS)),
    db: AsyncSession = Depends(get_db),
) -> RebatePeriodActualRead:
    agreement = await _get_agreement(db, agreement_public_id)
    period_actual = await _get_period_actual(db, agreement.id, period_public_id)
    closed = await rebate_service.close_period(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, period_actual=period_actual
    )
    derived = rebate_service.get_derived_progress(agreement, closed)
    return RebatePeriodActualRead(**RebatePeriodActualRead.model_validate(closed).model_dump(exclude={"next_tier_threshold", "amount_to_next_tier"}), **derived)


@router.post("/{agreement_public_id}/periods/{period_public_id}/receipt", response_model=RebateReceiptRecordResponse)
async def record_rebate_receipt(
    agreement_public_id: str, period_public_id: str, payload: RebateReceiptRecord,
    claims: AccessTokenClaims = Depends(require_permission(Permission.APPROVE_SAVINGS)),
    db: AsyncSession = Depends(get_db),
) -> RebateReceiptRecordResponse:
    agreement = await _get_agreement(db, agreement_public_id)
    period_actual = await _get_period_actual(db, agreement.id, period_public_id)
    result = await rebate_service.record_receipt(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id,
        period_actual=period_actual, payload=payload,
    )
    derived = rebate_service.get_derived_progress(agreement, result["period_actual"])
    period_actual_read = RebatePeriodActualRead(
        **RebatePeriodActualRead.model_validate(result["period_actual"]).model_dump(
            exclude={"next_tier_threshold", "amount_to_next_tier"}
        ),
        **derived,
    )
    return RebateReceiptRecordResponse(period_actual=period_actual_read, leakage_result=result["leakage_result"])
