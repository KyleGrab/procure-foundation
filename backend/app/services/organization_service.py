from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models import Organisation
from app.schemas.organization import OrganisationUpdate
from app.services import audit_service


async def get_current(db: AsyncSession, *, organisation_id: int) -> Organisation:
    result = await db.execute(select(Organisation).where(Organisation.id == organisation_id))
    org = result.scalar_one_or_none()
    if org is None:
        raise NotFoundError("Organisation not found")
    return org


async def update_current(
    db: AsyncSession, *, organisation_id: int, user_id: int, payload: OrganisationUpdate
) -> Organisation:
    org = await get_current(db, organisation_id=organisation_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(org, field, value)

    if changes:
        await audit_service.record(
            db,
            organisation_id=organisation_id,
            user_id=user_id,
            action="organisation_updated",
            entity_type="organisation",
            entity_id=str(organisation_id),
            context={"changed_fields": list(changes.keys())},
        )
    await db.commit()
    await db.refresh(org)
    return org
