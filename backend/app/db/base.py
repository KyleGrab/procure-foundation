"""
Declarative base + shared mixins. Every tenant-scoped model uses TenantScopedMixin so RLS
enablement and the organisation_id FK/index are never hand-rolled per-model (drifting from this
pattern is exactly how a table quietly loses tenant isolation - see ADR-003).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TenantScopedMixin(TimestampMixin):
    """
    Any model mixing this in MUST have a matching RLS policy created in its Alembic migration -
    enforced by the migration lint check referenced in ADR-003. See db/models/organization.py
    for the reference implementation of that migration pattern.
    """

    organisation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organisations.id"), nullable=False, index=True
    )
