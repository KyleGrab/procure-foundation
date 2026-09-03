from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """
    Insert-only by construction: the application DB role has no UPDATE/DELETE grant on this
    table at all (enforced in the Alembic migration, not just by omission from the ORM), making
    spec Section 54's "audit logs should be immutable to normal users" literal rather than a
    convention someone could accidentally violate.

    organisation_id is nullable because some actions (e.g. platform-level admin actions) aren't
    scoped to a single org - everything else always sets it.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    organisation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("organisations.id"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))

    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))

    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ip_address: Mapped[str | None] = mapped_column(INET)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
