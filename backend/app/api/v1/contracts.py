"""Contract API surface (spec Section 31-32, this delivery's Phase 3). Thin routes - logic lives
in services/contract_service.py per docs/architecture.md's rule."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Permission
from app.core.exceptions import NotFoundError
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims
from app.db.models import Contract, ContractExtraction, Supplier
from app.db.session import get_db
from app.schemas.contract import (
    ContractCreate,
    ContractExtractionVerify,
    ContractRead,
    EscalatedPriceRequest,
)
from app.services import contract_service

router = APIRouter(prefix="/contracts", tags=["contracts"])


def _to_read_model(contract: Contract, supplier_public_id) -> ContractRead:
    derived = contract_service.get_derived_fields(contract)
    return ContractRead(
        public_id=contract.public_id, supplier_public_id=supplier_public_id,
        title=contract.title, contract_number=contract.contract_number,
        start_date=contract.start_date, expiry_date=contract.expiry_date,
        notice_period_days=contract.notice_period_days, notice_deadline=derived["notice_deadline"],
        auto_renew=contract.auto_renew, renewal_term_months=contract.renewal_term_months,
        next_renewal_date=derived["next_renewal_date"], currency=contract.currency,
        escalation_type=contract.escalation_type, escalation_rate_pct=contract.escalation_rate_pct,
        status=contract.status, status_calculated_at=contract.status_calculated_at,
    )


async def _get_contract(db: AsyncSession, public_id: str) -> Contract:
    result = await db.execute(select(Contract).where(Contract.public_id == public_id))
    contract = result.scalar_one_or_none()
    if contract is None:
        raise NotFoundError("Contract not found")
    return contract


@router.post("", response_model=ContractRead, status_code=201)
async def create_contract(
    payload: ContractCreate,
    claims: AccessTokenClaims = Depends(require_permission(Permission.EDIT_SUPPLIERS)),
    db: AsyncSession = Depends(get_db),
) -> ContractRead:
    contract = await contract_service.create_contract(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, payload=payload
    )
    return _to_read_model(contract, payload.supplier_public_id)


@router.get("", response_model=list[ContractRead])
async def list_contracts(
    status: str | None = None,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_CONTRACTS)),
    db: AsyncSession = Depends(get_db),
) -> list[ContractRead]:
    """?status=expiring_soon etc. - status is always recomputed before being returned (ADR-010),
    never trusted as-stored, even though the stored value is what the filter itself queries on
    (a daily refresh job, per ADR-010's note, is what keeps the two from drifting apart in
    production)."""
    query = select(Contract, Supplier.public_id).join(Supplier, Supplier.id == Contract.supplier_id)
    if status:
        query = query.where(Contract.status == status)
    result = await db.execute(query)
    read_models = []
    for contract, supplier_public_id in result.all():
        contract_service.refresh_status(contract)
        read_models.append(_to_read_model(contract, supplier_public_id))
    return read_models


@router.get("/{contract_public_id}", response_model=ContractRead)
async def get_contract(
    contract_public_id: str,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_CONTRACTS)),
    db: AsyncSession = Depends(get_db),
) -> ContractRead:
    contract = await _get_contract(db, contract_public_id)
    supplier_result = await db.execute(select(Supplier.public_id).where(Supplier.id == contract.supplier_id))
    contract_service.refresh_status(contract)
    return _to_read_model(contract, supplier_result.scalar_one())


@router.post("/{contract_public_id}/escalated-price")
async def calculate_escalated_price_endpoint(
    contract_public_id: str, payload: EscalatedPriceRequest,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    contract = await _get_contract(db, contract_public_id)
    escalated = await contract_service.calculate_escalated_price_for_contract(
        db, contract=contract, base_price=payload.base_price,
        periods_elapsed=payload.periods_elapsed,
        external_index_value_pct=payload.external_index_value_pct,
    )
    return {"escalated_price": str(escalated)}


@router.post("/{contract_public_id}/check-alerts")
async def check_contract_alerts(
    contract_public_id: str,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_CONTRACTS)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manual trigger in this delivery - a scheduled daily job (Phase 9) is what should call this
    in production, not a user clicking a button. See app.services.contract_service.run_alert_check."""
    contract = await _get_contract(db, contract_public_id)
    new_alerts = await contract_service.run_alert_check(
        db, organisation_id=claims.active_org_id, contract=contract
    )
    return {"new_alerts": [a.alert_type for a in new_alerts]}


@router.post("/{contract_public_id}/extractions/{extraction_id}/verify", response_model=ContractRead)
async def verify_contract_extraction(
    contract_public_id: str, extraction_id: int, payload: ContractExtractionVerify,
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_CONTRACTS)),
    db: AsyncSession = Depends(get_db),
) -> ContractRead:
    contract = await _get_contract(db, contract_public_id)
    extraction_result = await db.execute(
        select(ContractExtraction).where(ContractExtraction.id == extraction_id)
    )
    extraction = extraction_result.scalar_one_or_none()
    if extraction is None:
        raise NotFoundError("Extraction not found")

    updated = await contract_service.promote_extraction_fields(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id,
        extraction=extraction, contract=contract, field_names=payload.field_names_to_promote,
    )
    supplier_result = await db.execute(select(Supplier.public_id).where(Supplier.id == updated.supplier_id))
    return _to_read_model(updated, supplier_result.scalar_one())
