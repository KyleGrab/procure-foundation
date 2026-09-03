from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Permission
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims
from app.db.session import get_db
from app.schemas.supplier import SupplierCreate, SupplierRead
from app.services import supplier_service

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("", response_model=list[SupplierRead])
async def list_suppliers(
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> list[SupplierRead]:
    suppliers = await supplier_service.list_suppliers(db, organisation_id=claims.active_org_id)
    return [SupplierRead.model_validate(s) for s in suppliers]


@router.post("", response_model=SupplierRead, status_code=201)
async def create_supplier(
    payload: SupplierCreate,
    claims: AccessTokenClaims = Depends(require_permission(Permission.EDIT_SUPPLIERS)),
    db: AsyncSession = Depends(get_db),
) -> SupplierRead:
    supplier = await supplier_service.create(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, payload=payload
    )
    return SupplierRead.model_validate(supplier)
