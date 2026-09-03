from __future__ import annotations

import uuid

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class Location(Base, TenantScopedMixin):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location_type: Mapped[str] = mapped_column(String(32), nullable=False)

    address: Mapped[str | None] = mapped_column(String(512))
    province: Mapped[str | None] = mapped_column(String(128))
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="ZA")

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
