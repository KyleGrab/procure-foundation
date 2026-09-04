"""
Registration, login, refresh, and org-switch. This is the module where docs/security.md
sections 1 and 3.1 become executable: Argon2id hashing, short-lived org-scoped access tokens,
rotated refresh tokens, and an explicit, audited org-switch rather than a fat multi-org token.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import MembershipStatus, Role
from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    PermissionDeniedError,
    RegistrationDisabledError,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.db.models import Organisation, OrganisationMembership, RefreshToken, User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenPair
from app.services import audit_service


def _hash_token(token: str) -> str:
    # Refresh tokens are already high-entropy JWTs; SHA-256 is sufficient here (unlike password
    # hashing, this isn't defending against a human-guessable secret) and keeps lookups cheap.
    return hashlib.sha256(token.encode()).hexdigest()


async def register(db: AsyncSession, payload: RegisterRequest) -> TokenPair:
    # D-01: checked first, before any query or write - a controlled demo environment must never
    # create an organisation or user via this path, not even transiently before failing.
    if not get_settings().allow_self_registration:
        raise RegistrationDisabledError("Self-registration is disabled in this environment.")

    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("An account with this email already exists")

    user = User(
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    await db.flush()  # populate user.id without committing

    organisation = Organisation(name=payload.organisation_name)
    db.add(organisation)
    await db.flush()

    membership = OrganisationMembership(
        user_id=user.id,
        organisation_id=organisation.id,
        role=Role.OWNER.value,
        status=MembershipStatus.ACTIVE.value,
    )
    db.add(membership)

    await audit_service.record(
        db,
        organisation_id=organisation.id,
        user_id=user.id,
        action="organisation_registered",
        entity_type="organisation",
        entity_id=str(organisation.id),
    )

    tokens = await _issue_tokens(db, user_id=user.id, organisation_id=organisation.id, role=Role.OWNER.value)
    await db.commit()
    return tokens


async def login(db: AsyncSession, payload: LoginRequest) -> TokenPair:
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None or not user.active or not verify_password(payload.password, user.password_hash):
        raise AuthenticationError("Invalid email or password")

    membership_result = await db.execute(
        select(OrganisationMembership)
        .where(OrganisationMembership.user_id == user.id)
        .where(OrganisationMembership.status == MembershipStatus.ACTIVE.value)
        .order_by(OrganisationMembership.created_at)
    )
    membership = membership_result.scalars().first()
    if membership is None:
        raise AuthenticationError("No active organisation membership for this user")

    user.last_login_at = datetime.now(UTC)

    tokens = await _issue_tokens(
        db, user_id=user.id, organisation_id=membership.organisation_id, role=membership.role
    )
    await db.commit()
    return tokens


async def switch_organisation(
    db: AsyncSession, *, user_id: int, target_organisation_public_id: uuid.UUID
) -> TokenPair:
    """
    See ADR-007: this is the ONLY way a user's active org context changes. It issues a fresh,
    narrowly-scoped token rather than the client selecting from a token that already knows every
    org the user belongs to.
    """
    result = await db.execute(
        select(OrganisationMembership, Organisation)
        .join(Organisation, Organisation.id == OrganisationMembership.organisation_id)
        .where(OrganisationMembership.user_id == user_id)
        .where(Organisation.public_id == target_organisation_public_id)
    )
    row = result.first()
    if row is None:
        raise PermissionDeniedError("No membership found for the requested organisation")
    membership, organisation = row
    if membership.status != MembershipStatus.ACTIVE.value:
        raise PermissionDeniedError("Membership is not active")

    await audit_service.record(
        db,
        organisation_id=organisation.id,
        user_id=user_id,
        action="org_context_switch",
        entity_type="organisation",
        entity_id=str(organisation.id),
    )

    tokens = await _issue_tokens(
        db, user_id=user_id, organisation_id=organisation.id, role=membership.role
    )
    await db.commit()
    return tokens


async def _issue_tokens(db: AsyncSession, *, user_id: int, organisation_id: int, role: str) -> TokenPair:
    settings = get_settings()
    access_token = create_access_token(user_id=user_id, active_org_id=organisation_id, role=role)

    family_id = uuid.uuid4()
    refresh_token = create_refresh_token(user_id=user_id, family_id=str(family_id))
    db.add(
        RefreshToken(
            user_id=user_id,
            family_id=family_id,
            token_hash=_hash_token(refresh_token),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    return TokenPair(access_token=access_token, refresh_token=refresh_token)
