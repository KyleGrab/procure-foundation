from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class OrganisationSetting(Base, TenantScopedMixin):
    """
    Structured, append-only settings - deliberately NOT a single JSON blob on Organisation.
    Every change is a new row (never an UPDATE), so "who changed the margin target and when" is
    always answerable from the table itself, satisfying the audit requirement (spec Section 54)
    for exactly the kind of setting that feeds a financial calculation. See ADR-004 context in
    docs/architecture.md section 2.4.
    """

    __tablename__ = "organisation_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    set_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    audit_log_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("audit_logs.id"))
