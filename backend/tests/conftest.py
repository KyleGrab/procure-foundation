"""
Test fixtures. Requires a real Postgres (RLS policies are meaningless against SQLite/mocks -
tenant isolation is exactly the thing we can't fake our way past in tests) so these run against
docker compose's postgres service, on a dedicated test database, never the dev database.
"""
from __future__ import annotations

import os

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://procureiq:procureiq@localhost:5432/procureiq_test")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql+psycopg://procureiq:procureiq@localhost:5432/procureiq_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use-only")

from app.db.base import Base  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _prepare_schema():
    from app.core.config import get_settings

    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test/api/v1") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session():
    """
    Raw AsyncSession against the same admin database_url _prepare_schema uses (not
    database_url_app) - for tests that need to set up data no ingestion API exists for yet
    (e.g. management-accounting demo seeding). Deliberately the admin connection, same as schema
    setup: seeding demo data is an admin-level operation, not something a real tenant's app-role
    session should ever need to do - RLS still correctly scopes what the `client` fixture's HTTP
    requests can read afterward, since those go through the real app-role connection under a
    real JWT's organisation_id, regardless of which connection wrote the row.
    """
    from app.core.config import get_settings

    engine = create_async_engine(get_settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


def _sync_dsn_as_plain_url() -> str:
    """DATABASE_URL_SYNC is 'postgresql+psycopg://...' (SQLAlchemy dialect prefix) - psycopg's
    own AsyncConnection.connect() wants a bare 'postgresql://' DSN, not the SQLAlchemy form."""
    from app.core.config import get_settings

    return get_settings().database_url_sync.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest_asyncio.fixture
async def db_conn():
    """
    P-03: a raw, single psycopg async connection - deliberately NOT the ORM (no AsyncSession,
    no model classes). The raw-SQL constraint/trigger tests need to observe real PostgreSQL
    exceptions (CHECK constraint names, trigger RAISE EXCEPTION messages) directly, not
    SQLAlchemy's wrapped/translated versions, and need explicit BEGIN/COMMIT control that
    matches how a deferred constraint trigger actually behaves (checked at COMMIT, not at the
    point of INSERT) - same reasoning as tests/test_rls_integration.py's existing raw-psycopg
    pattern, extended to async since these tests are async throughout.
    """
    import psycopg

    async with await psycopg.AsyncConnection.connect(_sync_dsn_as_plain_url(), autocommit=False) as conn:
        yield conn


@pytest_asyncio.fixture
async def db_conn_a():
    """P-03: first of two genuinely independent connections for the concurrency test - a second
    connection object from the same fixture would share a session, not exercise real
    cross-connection locking."""
    import psycopg

    async with await psycopg.AsyncConnection.connect(_sync_dsn_as_plain_url(), autocommit=False) as conn:
        yield conn


@pytest_asyncio.fixture
async def db_conn_b():
    """P-03: second of the two connections - see db_conn_a."""
    import psycopg

    async with await psycopg.AsyncConnection.connect(_sync_dsn_as_plain_url(), autocommit=False) as conn:
        yield conn


@pytest_asyncio.fixture
async def p03_seed(db_session):
    """
    P-03: real rows the raw-SQL test suite needs, created once per test via the ORM (this
    fixture runs against the FULLY-MIGRATED test database - head, including 0021 - unlike the
    separate migration-compatibility script, which deliberately never touches the ORM). Returns
    real IDs rather than hardcoded constants, since every CI run gets a genuinely fresh database.
    """
    from datetime import date

    from app.db.models import (
        Opportunity, Organisation, OrganisationMembership, RebateAgreement, RebatePeriodActual, User,
    )

    org_a = Organisation(name="P-03 Test Org A", default_currency="ZAR", country="ZA")
    org_b = Organisation(name="P-03 Test Org B", default_currency="ZAR", country="ZA")
    db_session.add_all([org_a, org_b])
    await db_session.flush()

    user = User(first_name="P03", last_name="Seed", email="p03-seed@procureiq.local",
                password_hash="not-a-real-hash-seed-only", verified=True)
    db_session.add(user)
    await db_session.flush()
    db_session.add(OrganisationMembership(user_id=user.id, organisation_id=org_a.id, role="owner", status="active"))
    await db_session.flush()

    agreement = RebateAgreement(
        organisation_id=org_a.id, supplier_id=None, title="P-03 Test Agreement",
        rebate_type="fixed_percentage", period_type="quarterly", flat_rate_pct="0.02",
        currency="ZAR", created_by_user_id=user.id,
    )
    db_session.add(agreement)
    await db_session.flush()

    period_actual = RebatePeriodActual(
        organisation_id=org_a.id, rebate_agreement_id=agreement.id,
        period_start=date(2026, 1, 1), period_end=date(2026, 3, 31),
        entry_source="manual", entered_by_user_id=user.id, expected_amount_status="unknown",
    )
    db_session.add(period_actual)
    await db_session.flush()

    opportunity = Opportunity(
        organisation_id=org_a.id, title="P-03 Test Opportunity", opportunity_type="price_increase_challenge",
        status="identified", created_by_user_id=user.id,
        annual_financial_impact_status="unknown", realised_savings_status="unknown",
    )
    db_session.add(opportunity)
    await db_session.flush()

    genesis_event = await db_session.execute(
        __import__("sqlalchemy").text(
            "INSERT INTO financial_amount_status_events (organisation_id, rebate_period_actual_id, "
            "measure_code, event_version, new_status, occurred_at, change_reference, change_reason_code) "
            "VALUES (:org, :parent, 'expected_amount', 1, 'unknown', now(), 'p03_seed_fixture', 'initial_backfill') "
            "RETURNING id"
        ),
        {"org": org_a.id, "parent": period_actual.id},
    )
    event_id = genesis_event.scalar_one()
    await db_session.execute(
        __import__("sqlalchemy").text(
            "UPDATE rebate_period_actuals SET expected_amount_current_event_id = :ev WHERE id = :pid"
        ),
        {"ev": event_id, "pid": period_actual.id},
    )
    await db_session.commit()

    class Seed:
        org_id = org_a.id
        org_a_id = org_a.id
        org_b_id = org_b.id
        user_id = user.id
        agreement_id = agreement.id
        period_actual_id = period_actual.id
        opportunity_id = opportunity.id
        event_id = event_id

    return Seed()
