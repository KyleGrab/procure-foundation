from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidAuditIdentifierError
from app.db.models import AuditLog

# AUDIT-ENTITY-ID-R2: audit_logs.entity_id is a real, fixed VARCHAR(64) column (migration 0001) -
# every supported identifier a caller may pass is canonicalised to that same text form here, once,
# rather than trusted to already be a str at every one of this function's ~30 call sites (two of
# them, treasury_service.py and route_profitability_service.py, previously weren't - both passed
# a bare int straight through, which asyncpg's own strict VARCHAR binding rejects at commit as a
# raw, unhandled DataError instead of a diagnosed application error).
_SupportedEntityId = str | int | uuid.UUID


def _canonicalize_entity_id(entity_id: _SupportedEntityId | None) -> str | None:
    """None stays None (a real, deliberate "no single target row" case - several existing call
    sites rely on this). A bool is deliberately never accepted even though Python's bool is
    technically an int subclass - the isinstance(entity_id, bool) check must run before the int
    check, or True/False would silently canonicalise to "True"/"False", almost certainly the
    wrong variable at the call site rather than a genuine identifier.

    Deliberately not a blanket str(entity_id): an unsupported type (an ORM object, a dict, a
    list, ...) almost always means a real caller mistake - the wrong variable, or an object
    passed where its id was meant - and a permissive str() would silently persist an unhelpful
    repr() as if it were a real identifier instead of surfacing that mistake immediately."""
    if entity_id is None:
        return None
    if isinstance(entity_id, bool):
        raise InvalidAuditIdentifierError(
            f"Unsupported audit entity_id type: bool ({entity_id!r}) - expected str, int, uuid.UUID, or None"
        )
    if isinstance(entity_id, (str, int, uuid.UUID)):
        return str(entity_id)
    raise InvalidAuditIdentifierError(
        f"Unsupported audit entity_id type: {type(entity_id).__name__} - expected str, int, uuid.UUID, or None"
    )


async def record(
    db: AsyncSession,
    *,
    organisation_id: int | None,
    user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: _SupportedEntityId | None = None,
    context: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """
    Every call site listed against a spec requirement, so it's obvious nothing critical is
    un-audited: uploads/imports (10), deletions (54), price approvals (83), savings approvals
    (35), opportunity changes (33), contract changes (31), role changes (8), exports (54),
    org-context switches (ADR-007), settings changes (ADR-004).

    entity_id accepts str, int, uuid.UUID, or None - canonicalised to the column's real text form
    before the ORM ever sees it (see _canonicalize_entity_id). This function still adds the row
    to the session and lets the caller's own commit persist it, exactly as before - audit writes
    remain mandatory and share the caller's transaction; that coupling is a separate design
    decision, not something this change touches.
    """
    db.add(
        AuditLog(
            organisation_id=organisation_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=_canonicalize_entity_id(entity_id),
            context=context or {},
            ip_address=ip_address,
        )
    )
