"""
BUSINESS-DATE-SEMANTICS-IMPLEMENTATION-R1: resolves an organisation's current business-calendar
date from its own configured IANA timezone (Organisation.timezone) - the one deliberately
permitted place "today" may be read from a real clock (see the design phase's rule #3: current
date may be derived only at an outer application boundary, and only from an organisation-
configured timezone). Every approved service boundary reads this exactly once per request, then
threads the resulting as_of_date through explicitly - never re-derived deeper in the call stack,
the same determinism-boundary discipline §2.1 already applies to DB sessions and RLS context.

Deliberately framework-free (no sqlalchemy/fastapi import) - the DB lookup of an organisation's
own timezone value lives at the call site (app.db.session), not here.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.exceptions import ProcureIQError


class InvalidBusinessTimezoneError(ProcureIQError):
    """
    Raised by resolve_business_date when the supplied timezone name isn't a real IANA zone, or
    a caller-supplied instant isn't both timezone-aware and genuinely UTC. Both are always an
    internal-caller/data-integrity bug in this delivery - no route accepts a client-supplied
    timezone or instant (BUSINESS-DATE-SEMANTICS-IMPLEMENTATION-R1 explicitly excludes a client-
    controlled as_of_date override), so this can only fire from a corrupted Organisation.timezone
    value already in the database, or a real internal mistake - never something request input can
    trigger directly. 500, not a 4xx - same reasoning as InvalidAuditIdentifierError.
    """

    code = "invalid_business_timezone"
    status_code = 500


def resolve_business_date(organisation_timezone: str, *, utc_instant: datetime | None = None) -> date:
    """
    The only place in this codebase permitted to read a real clock for business-calendar
    purposes. utc_instant defaults to the actual current instant (datetime.now(UTC)) - the sole
    legitimate wall-clock read - and is otherwise accepted only so tests can supply a fixed,
    deterministic instant; it is never "optional" in the sense of falling back to something else
    if given - a naive or non-UTC instant is rejected outright, never silently reinterpreted as
    UTC or as server-local time.
    """
    if utc_instant is None:
        utc_instant = datetime.now(UTC)
    elif utc_instant.tzinfo is None or utc_instant.utcoffset() != timedelta(0):
        raise InvalidBusinessTimezoneError(
            f"utc_instant must be an aware, genuinely-UTC datetime, got {utc_instant!r}"
        )

    try:
        zone = ZoneInfo(organisation_timezone)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise InvalidBusinessTimezoneError(
            f"{organisation_timezone!r} is not a valid IANA timezone name"
        ) from exc

    return utc_instant.astimezone(zone).date()
