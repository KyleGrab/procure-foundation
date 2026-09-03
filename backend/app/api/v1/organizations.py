from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Permission
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims
from app.db.session import get_db
from app.schemas.organization import OrganisationRead, OrganisationUpdate
from app.services import organization_service

router = APIRouter(prefix="/organisations", tags=["organisations"])


@router.get("/current", response_model=OrganisationRead)
async def get_current_organisation(
    claims: AccessTokenClaims = Depends(require_permission(Permission.VIEW_FINANCIALS)),
    db: AsyncSession = Depends(get_db),
) -> OrganisationRead:
    org = await organization_service.get_current(db, organisation_id=claims.active_org_id)
    return OrganisationRead.model_validate(org)


@router.patch("/current", response_model=OrganisationRead)
async def update_current_organisation(
    payload: OrganisationUpdate,
    claims: AccessTokenClaims = Depends(require_permission(Permission.MANAGE_ORGANISATION)),
    db: AsyncSession = Depends(get_db),
) -> OrganisationRead:
    org = await organization_service.update_current(
        db, organisation_id=claims.active_org_id, user_id=claims.user_id, payload=payload
    )
    return OrganisationRead.model_validate(org)
