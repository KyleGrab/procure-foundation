from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog


async def record(
    db: AsyncSession,
    *,
    organisation_id: int | None,
    user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    context: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """
    Every call site listed against a spec requirement, so it's obvious nothing critical is
    un-audited: uploads/imports (10), deletions (54), price approvals (83), savings approvals
    (35), opportunity changes (33), contract changes (31), role changes (8), exports (54),
    org-context switches (ADR-007), settings changes (ADR-004).
    """
    db.add(
        AuditLog(
            organisation_id=organisation_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            context=context or {},
            ip_address=ip_address,
        )
    )
