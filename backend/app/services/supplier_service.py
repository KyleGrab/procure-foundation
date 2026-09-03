from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models import Supplier
from app.schemas.supplier import SupplierCreate
from app.services import audit_service


async def create(db: AsyncSession, *, organisation_id: int, user_id: int, payload: SupplierCreate) -> Supplier:
    supplier = Supplier(organisation_id=organisation_id, **payload.model_dump())
    db.add(supplier)
    await db.flush()
    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id, action="supplier_created",
        entity_type="supplier", entity_id=str(supplier.id),
    )
    await db.commit()
    await db.refresh(supplier)
    return supplier


async def list_suppliers(db: AsyncSession, *, organisation_id: int) -> list[Supplier]:
    result = await db.execute(
        select(Supplier).where(Supplier.deleted_at.is_(None)).order_by(Supplier.legal_name)
    )
    return list(result.scalars().all())


async def get_by_public_id(db: AsyncSession, *, public_id: str) -> Supplier:
    result = await db.execute(select(Supplier).where(Supplier.public_id == public_id))
    supplier = result.scalar_one_or_none()
    if supplier is None:
        raise NotFoundError("Supplier not found")
    return supplier
