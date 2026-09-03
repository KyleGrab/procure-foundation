"""
Organisation is the tenant root. It is NOT itself tenant-scoped (there's no organisation_id on
organisations - it IS the organisation). Every other tenant-scoped model's RLS policy ultimately
resolves against this table's id. See docs/data-model.md section 2 and ADR-003/ADR-005.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Organisation(Base, TimestampMixin):
    __tablename__ = "organisations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255))
    registration_number: Mapped[str | None] = mapped_column(String(64))
    tax_number: Mapped[str | None] = mapped_column(String(64))

    default_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ZAR")
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="ZA")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Africa/Johannesburg")

    industry: Mapped[str | None] = mapped_column(String(128))
    annual_procurement_spend: Mapped[float | None] = mapped_column(Numeric(18, 4))
    fiscal_year_start: Mapped[date | None] = mapped_column(Date)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Branding only - never a value that feeds a financial calculation. Anything that does
    # (thresholds, weights, rounding, target margins) belongs in OrganisationSetting instead,
    # where changes are versioned and audited. See ADR-004 in docs/decisions/.
    branding_app_name: Mapped[str] = mapped_column(String(64), nullable=False, default="ProcureIQ")
    branding_logo_url: Mapped[str | None] = mapped_column(String(512))
