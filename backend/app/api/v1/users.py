import secrets

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import MembershipStatus, Permission
from app.core.exceptions import ConflictError, NotFoundError
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims, hash_password
from app.db.models import OrganisationMembership, User
from app.db.session import get_db
from app.schemas.user import MembershipRead, MembershipUpdate, UserInvite
from app.services import audit_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[MembershipRead])
async def list_users(
    claims: AccessTokenClaims = Depends(require_permission(Permission.MANAGE_USERS)),
    db: AsyncSession = Depends(get_db),
) -> list[MembershipRead]:
    result = await db.execute(
        select(OrganisationMembership, User)
        .join(User, User.id == OrganisationMembership.user_id)
        .where(OrganisationMembership.organisation_id == claims.active_org_id)
    )
    return [
        MembershipRead(
            public_id=membership.public_id,
            user_public_id=user.public_id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            role=membership.role,
            status=membership.status,
        )
        for membership, user in result.all()
    ]


@router.post("/invite", response_model=MembershipRead, status_code=201)
async def invite_user(
    payload: UserInvite,
    claims: AccessTokenClaims = Depends(require_permission(Permission.MANAGE_USERS)),
    db: AsyncSession = Depends(get_db),
) -> MembershipRead:
    existing = await db.execute(select(User).where(User.email == payload.email))
    user = existing.scalar_one_or_none()

    if user is None:
        # Placeholder password - invited users complete setup via the password-reset flow
        # (Phase 1 password-reset endpoints), never receive a real password over email.
        user = User(
            first_name=payload.first_name,
            last_name=payload.last_name,
            email=payload.email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            verified=False,
        )
        db.add(user)
        await db.flush()
    else:
        dup = await db.execute(
            select(OrganisationMembership)
            .where(OrganisationMembership.user_id == user.id)
            .where(OrganisationMembership.organisation_id == claims.active_org_id)
        )
        if dup.scalar_one_or_none() is not None:
            raise ConflictError("User is already a member of this organisation")

    membership = OrganisationMembership(
        user_id=user.id,
        organisation_id=claims.active_org_id,
        role=payload.role,
        status=MembershipStatus.INVITED.value,
        invited_by_user_id=claims.user_id,
    )
    db.add(membership)
    await db.flush()

    await audit_service.record(
        db,
        organisation_id=claims.active_org_id,
        user_id=claims.user_id,
        action="user_invited",
        entity_type="organisation_membership",
        entity_id=str(membership.id),
        context={"invited_email": payload.email, "role": payload.role},
    )
    await db.commit()

    return MembershipRead(
        public_id=membership.public_id,
        user_public_id=user.public_id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role=membership.role,
        status=membership.status,
    )


@router.patch("/{membership_public_id}", response_model=MembershipRead)
async def update_membership(
    membership_public_id: str,
    payload: MembershipUpdate,
    claims: AccessTokenClaims = Depends(require_permission(Permission.MANAGE_USERS)),
    db: AsyncSession = Depends(get_db),
) -> MembershipRead:
    result = await db.execute(
        select(OrganisationMembership, User)
        .join(User, User.id == OrganisationMembership.user_id)
        .where(OrganisationMembership.public_id == membership_public_id)
        .where(OrganisationMembership.organisation_id == claims.active_org_id)
    )
    row = result.first()
    if row is None:
        raise NotFoundError("Membership not found")
    membership, user = row

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(membership, field, value)

    if changes:
        await audit_service.record(
            db,
            organisation_id=claims.active_org_id,
            user_id=claims.user_id,
            action="membership_updated",
            entity_type="organisation_membership",
            entity_id=str(membership.id),
            context={"changed_fields": list(changes.keys())},
        )
    await db.commit()

    return MembershipRead(
        public_id=membership.public_id,
        user_public_id=user.public_id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role=membership.role,
        status=membership.status,
    )
