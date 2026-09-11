"""
DB session dependency + the RLS session-variable wiring described in docs/security.md section 3.
Every request that touches tenant-scoped data goes through get_db, which:
  1. decodes and validates the JWT (get_current_claims)
  2. opens a DB session
  3. sets `app.current_org_id` on EVERY transaction that session opens, from the token's
     active_org_id claim - never from a client-supplied header, query param, or path segment.
This is what makes RLS policies (ADR-003) actually bind to the authenticated user's org, not
just "whatever org id happened to be passed in."

RLS-TXN-R1: point 3 used to be a single explicit SELECT set_config(...) issued once, right after
the session opened. set_config's third arg (is_local=true) is SET LOCAL semantics - scoped to
the CURRENT transaction only, by design, so it can never leak across pooled connections between
requests. But that also means it never survived a service calling db.commit() mid-request: commit
ends the transaction the context was set on, and the next statement silently autobegins a new,
context-free transaction. RLS then - correctly, precisely because the GUC really is unset -
denies visibility into rows this same request just wrote, which SQLAlchemy surfaces as
InvalidRequestError ("Could not refresh instance") out of db.refresh(), among other symptoms.

The fix is structural, not a per-service reorder: a `Session.after_begin` event, scoped to a
dedicated sync_session_class used only by this module's sessionmaker, re-applies the request's
org_id (from `session.info`, not a global) to EVERY transaction the session opens - the first one
and every one after a commit or rollback. is_local=true is preserved throughout, so the pool
safety property is unchanged (Postgres itself clears a transaction-local GUC when that
transaction ends, regardless of why). A session with no org_id in `.info` (get_db_unauthenticated)
gets no automatic set_config at all - RLS then denies everything by default, which is the correct,
existing fail-closed behavior for that path; see auth_service.py's own narratively-gated
set_current_user_id/set_current_org_id calls, which this change does not touch.

Both dependencies below map only a genuine session-open/initial-transaction failure to
DatabaseUnavailableError (503) - forcing that first transaction to begin eagerly (`await
session.connection()`) isolates it from whatever the route/service does with the session
afterward. A real error raised by route/service code (a bad request, a genuine constraint
violation, a real bug) now propagates with its own correct exception semantics instead of being
flattened into an unrelated "database unavailable" - see docs/security.md section 3 note on error
boundaries.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends, Header
from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, DatabaseUnavailableError
from app.core.security import AccessTokenClaims, decode_access_token

_settings = get_settings()
# ADR-011: the application connects as procureiq_app (least-privilege, RLS-forced), never as the
# admin/migration role - database_url_app, not database_url, is what actually serves requests.
_engine = create_async_engine(_settings.database_url_app, pool_pre_ping=True)

# A dedicated sync Session subclass, used only by _session_factory below, so the after_begin
# listener registered on it applies only to sessions this module creates - never to some other,
# unrelated sync Session anywhere else in the process.
_ORG_ID_INFO_KEY = "rls_txn_r1_app_current_org_id"


class _TenantScopedSession(Session):
    pass


@event.listens_for(_TenantScopedSession, "after_begin")
def _apply_tenant_context(session: Session, transaction, connection) -> None:
    """Fires at the start of every transaction this session opens (the first one, and every one
    after a commit or rollback - not just once at session creation). Reads the org id the request
    validated up front (get_db) and stashed on `session.info` - never a module-global, never
    re-derived from anything client-supplied here. A session with no org id in `.info`
    (get_db_unauthenticated) gets no set_config call at all, leaving RLS's normal fail-closed
    behavior untouched for that path."""
    org_id = session.info.get(_ORG_ID_INFO_KEY)
    if org_id is None:
        return
    connection.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"), {"org_id": str(org_id)}
    )


_session_factory = async_sessionmaker(_engine, expire_on_commit=False, sync_session_class=_TenantScopedSession)


async def get_current_claims(authorization: str | None = Header(default=None)) -> AccessTokenClaims:
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthenticationError("Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    return decode_access_token(token)


async def get_db(
    claims: AccessTokenClaims = Depends(get_current_claims),
) -> AsyncGenerator[AsyncSession, None]:
    session = _session_factory()
    # Request-scoped, not a global: this dict lives only on this one AsyncSession instance, which
    # get_db creates fresh per request and closes at the end of this generator.
    session.sync_session.info[_ORG_ID_INFO_KEY] = claims.active_org_id
    try:
        # Eagerly open the connection and begin the first transaction now (firing
        # _apply_tenant_context) rather than lazily on the route's first query - isolates a
        # genuine connection/context-setup failure from anything the route/service does next.
        await session.connection()
    except SQLAlchemyError as exc:
        await session.close()
        raise DatabaseUnavailableError("Database temporarily unavailable") from exc
    try:
        yield session
    finally:
        await session.close()


async def get_db_unauthenticated() -> AsyncGenerator[AsyncSession, None]:
    """For endpoints that run before an org context exists at all: register, login. These must
    never query a tenant-scoped table directly - only organisations/users/memberships during
    creation, which are guarded by application logic, not RLS, at that specific moment."""
    session = _session_factory()
    try:
        await session.connection()
    except SQLAlchemyError as exc:
        await session.close()
        raise DatabaseUnavailableError("Database temporarily unavailable") from exc
    try:
        yield session
    finally:
        await session.close()
