"""
DB session dependency + the RLS session-variable wiring described in docs/security.md section 3.
Every request that touches tenant-scoped data goes through get_db, which:
  1. decodes and validates the JWT (get_current_claims)
  2. opens a DB session
  3. sets `app.current_org_id` on that session's Postgres connection from the token's
     active_org_id claim - never from a client-supplied header, query param, or path segment.
This is what makes RLS policies (ADR-003) actually bind to the authenticated user's org, not
just "whatever org id happened to be passed in."

Both dependencies below catch SQLAlchemyError around session open/SET LOCAL and re-raise as
DatabaseUnavailableError (503) - a real, previously-unhandled gap (a Postgres connection failure
here would otherwise propagate as a raw, unhandled exception to every route sharing this
dependency, not just one feature).
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends, Header
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, DatabaseUnavailableError
from app.core.security import AccessTokenClaims, decode_access_token

_settings = get_settings()
# ADR-011: the application connects as procureiq_app (least-privilege, RLS-forced), never as the
# admin/migration role - database_url_app, not database_url, is what actually serves requests.
_engine = create_async_engine(_settings.database_url_app, pool_pre_ping=True)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def get_current_claims(authorization: str | None = Header(default=None)) -> AccessTokenClaims:
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthenticationError("Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    return decode_access_token(token)


async def get_db(
    claims: AccessTokenClaims = Depends(get_current_claims),
) -> AsyncGenerator[AsyncSession, None]:
    try:
        async with _session_factory() as session:
            # set_config's third arg (is_local=true) scopes the setting to this transaction
            # only, so it can never leak across pooled connections between requests.
            await session.execute(
                text("SELECT set_config('app.current_org_id', :org_id, true)"),
                {"org_id": str(claims.active_org_id)},
            )
            yield session
    except SQLAlchemyError as exc:
        raise DatabaseUnavailableError("Database temporarily unavailable") from exc


async def get_db_unauthenticated() -> AsyncGenerator[AsyncSession, None]:
    """For endpoints that run before an org context exists at all: register, login. These must
    never query a tenant-scoped table directly - only organisations/users/memberships during
    creation, which are guarded by application logic, not RLS, at that specific moment."""
    try:
        async with _session_factory() as session:
            yield session
    except SQLAlchemyError as exc:
        raise DatabaseUnavailableError("Database temporarily unavailable") from exc
