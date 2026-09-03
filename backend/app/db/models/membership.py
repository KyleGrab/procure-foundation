from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class OrganisationMembership(Base, TimestampMixin):
    """
    The join between users and organisations that makes multi-org consultants (spec 4.6)
    possible. Deliberately NOT embedded wholesale into the JWT - see ADR-007 and
    docs/security.md 3.1 for why the token only ever carries the *currently active* membership.
    """

    __tablename__ = "organisation_memberships"
    __table_args__ = (UniqueConstraint("user_id", "organisation_id", name="uq_user_org"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    organisation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organisations.id"), nullable=False
    )

    role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="invited")
    invited_by_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
