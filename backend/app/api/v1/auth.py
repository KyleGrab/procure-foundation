from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AccessTokenClaims
from app.db.models import Organisation, OrganisationMembership, User
from app.db.session import get_current_claims, get_db_unauthenticated
from app.schemas.auth import (
    CurrentUser,
    LoginRequest,
    MembershipSummary,
    RegisterRequest,
    SwitchOrgRequest,
    TokenPair,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenPair, status_code=201)
async def register(
    payload: RegisterRequest, db: AsyncSession = Depends(get_db_unauthenticated)
) -> TokenPair:
    return await auth_service.register(db, payload)


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db_unauthenticated)) -> TokenPair:
    return await auth_service.login(db, payload)


@router.post("/switch-org", response_model=TokenPair)
async def switch_org(
    payload: SwitchOrgRequest,
    claims: AccessTokenClaims = Depends(get_current_claims),
    db: AsyncSession = Depends(get_db_unauthenticated),
) -> TokenPair:
    return await auth_service.switch_organisation(
        db, user_id=claims.user_id, target_organisation_public_id=payload.organisation_public_id
    )


@router.get("/me", response_model=CurrentUser)
async def me(
    claims: AccessTokenClaims = Depends(get_current_claims),
    db: AsyncSession = Depends(get_db_unauthenticated),
) -> CurrentUser:
    result = await db.execute(select(User).where(User.id == claims.user_id))
    user = result.scalar_one()

    memberships_result = await db.execute(
        select(OrganisationMembership, Organisation)
        .join(Organisation, Organisation.id == OrganisationMembership.organisation_id)
        .where(OrganisationMembership.user_id == user.id)
    )
    memberships = [
        MembershipSummary(
            organisation_public_id=org.public_id,
            organisation_name=org.name,
            role=membership.role,
            status=membership.status,
        )
        for membership, org in memberships_result.all()
    ]

    return CurrentUser(
        public_id=user.public_id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        memberships=memberships,
    )
