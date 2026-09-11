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
# ADR-011: app/db/session.py (imported below via app.main) connects as procureiq_app, never as
# the admin role above - this must be set too or Settings() fails at import time before any test
# collects. Same dev-only credential alembic/versions/0004_least_privilege_app_role.py creates
# and docker-compose.yml's backend/worker services already use.
os.environ.setdefault(
    "DATABASE_URL_APP",
    "postgresql+asyncpg://procureiq_app:procureiq_app_dev_only_rotate_in_production@localhost:5432/procureiq_test",
)
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use-only")

from app.main import app  # noqa: E402


def _admin_maintenance_dsn(database_url_sync: str) -> str:
    """Bare 'postgresql://' DSN (psycopg wants this, not SQLAlchemy's 'postgresql+psycopg://'
    prefix) pointed at Postgres's 'postgres' maintenance database - the one database guaranteed
    to exist, and the one you must connect to in order to DROP/CREATE the actual target database
    (a session can't drop the database it's connected to)."""
    plain = database_url_sync.replace("postgresql+psycopg://", "postgresql://", 1)
    prefix, _, _dbname = plain.rpartition("/")
    return f"{prefix}/postgres"


@pytest.fixture(scope="session", autouse=True)
def _prepare_schema():
    """
    Real `alembic upgrade head`, not Base.metadata.create_all(): create_all only creates tables
    from the ORM's metadata - it never runs the raw op.execute() DDL every migration also carries
    (CREATE ROLE procureiq_app, GRANTs, ENABLE/FORCE ROW LEVEL SECURITY, triggers, extensions -
    see e.g. alembic/versions/0004_least_privilege_app_role.py). Every test in this suite
    ultimately depends on procureiq_app existing and being correctly privileged/RLS-forced
    (app/db/session.py connects as procureiq_app, never as the admin role - ADR-011), so the test
    database has to go through the exact same migration chain production does, not a schema-only
    shortcut.

    Deliberately a plain (non-async) fixture: DROP/CREATE DATABASE via a plain psycopg connection,
    then `alembic upgrade head` as a subprocess. Neither touches an asyncio event loop, so this
    session-scoped setup step shares no loop-bound state with the per-test async fixtures below.

    Fresh disposable database: dropped and recreated every session, never an accumulated/ambient
    database left over from a previous run.
    """
    import subprocess
    import sys
    from pathlib import Path

    import psycopg
    from psycopg import sql

    from app.core.config import get_settings

    settings = get_settings()
    db_name = settings.database_url_sync.rsplit("/", 1)[-1]

    with psycopg.connect(_admin_maintenance_dsn(settings.database_url_sync), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (db_name,),
            )
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_name)))
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))

    backend_root = Path(__file__).resolve().parent.parent
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_root,
        env={**os.environ, "DATABASE_URL": settings.database_url, "DATABASE_URL_SYNC": settings.database_url_sync},
        check=True,
    )
    yield


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

    Teardown rolls back rather than committing. A test proving one specific INSERT/UPDATE is
    accepted or rejected is a narrower claim than "this whole transaction survives every OTHER
    deferred trigger this row happens to carry" (e.g. migration 0024's parent-final-state
    triggers, which validate a touched opportunities/rebate_period_actuals row's CURRENT state
    unconditionally, for every governed measure, not only whichever one a given test is about).
    A test that genuinely needs to prove a transaction commits still does so explicitly - calling
    db_conn.commit() itself, or exiting a `.transaction()` context cleanly - independent of this
    teardown. Rolling back also leaves no residue in the session-scoped database for a later test
    to collide with.
    """
    import psycopg

    conn = await psycopg.AsyncConnection.connect(_sync_dsn_as_plain_url(), autocommit=False)
    try:
        yield conn
    finally:
        await conn.rollback()
        await conn.close()


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

    P03-CORE-R1 (migration 0024)'s parent-final-state triggers validate the CURRENT, final
    persisted row at commit - not just whichever statement fired them - so every governed measure
    a parent row this fixture creates and commits carries (RebatePeriodActual.expected_amount,
    Opportunity.annual_financial_impact, Opportunity.realised_savings) needs its own genesis event
    and a correctly pointing current_event_id before this fixture's own commit, regardless of
    which single measure an individual test actually exercises.
    """
    import uuid
    from datetime import date

    import sqlalchemy as sa

    from app.db.models import (
        Opportunity, Organisation, OrganisationMembership, RebateAgreement, RebatePeriodActual, Supplier, User,
    )

    org_a = Organisation(name="P-03 Test Org A", default_currency="ZAR", country="ZA")
    org_b = Organisation(name="P-03 Test Org B", default_currency="ZAR", country="ZA")
    db_session.add_all([org_a, org_b])
    await db_session.flush()

    # Unique per invocation: this fixture is function-scoped and commits its rows, and
    # users.email is unique - a fixed literal collides the second time any test using p03_seed
    # runs against the same session-scoped database.
    user = User(first_name="P03", last_name="Seed", email=f"p03-seed-{uuid.uuid4()}@procureiq.local",
                password_hash="not-a-real-hash-seed-only", verified=True)
    db_session.add(user)
    await db_session.flush()
    db_session.add(OrganisationMembership(user_id=user.id, organisation_id=org_a.id, role="owner", status="active"))
    await db_session.flush()

    # ck_rebate_agreements_supplier_or_customer requires exactly one of supplier_id/customer_id -
    # a minimal valid Supplier makes this buy-side agreement structurally valid without weakening
    # the production constraint.
    supplier = Supplier(organisation_id=org_a.id, legal_name="P-03 Test Supplier")
    db_session.add(supplier)
    await db_session.flush()

    agreement = RebateAgreement(
        organisation_id=org_a.id, supplier_id=supplier.id, title="P-03 Test Agreement",
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

    async def _genesis_event(*, rebate_period_actual_id=None, opportunity_id=None, measure_code):
        """A version-1 event: old_* fields all NULL (ck_famev_genesis_old_fields_null), new_*
        fields the 'unknown' branch of that measure's state-combination check - matching every
        parent row this fixture creates, all seeded at status='unknown'. public_id is supplied
        explicitly (gen_random_uuid()) - this is a raw INSERT bypassing the ORM's Python-side
        UUID default, and the column is NOT NULL with no server-side default."""
        result = await db_session.execute(
            sa.text(
                "INSERT INTO financial_amount_status_events (public_id, organisation_id, "
                "rebate_period_actual_id, opportunity_id, measure_code, event_version, new_status, "
                "occurred_at, change_reference, change_reason_code) "
                "VALUES (gen_random_uuid(), :org, :rpa, :opp, :measure, 1, 'unknown', now(), "
                "'p03_seed_fixture', 'initial_backfill') RETURNING id"
            ),
            {"org": org_a.id, "rpa": rebate_period_actual_id, "opp": opportunity_id, "measure": measure_code},
        )
        return result.scalar_one()

    expected_amount_event_id = await _genesis_event(
        rebate_period_actual_id=period_actual.id, measure_code="expected_amount"
    )
    await db_session.execute(
        sa.text("UPDATE rebate_period_actuals SET expected_amount_current_event_id = :ev WHERE id = :pid"),
        {"ev": expected_amount_event_id, "pid": period_actual.id},
    )

    afi_event_id = await _genesis_event(opportunity_id=opportunity.id, measure_code="annual_financial_impact")
    rs_event_id = await _genesis_event(opportunity_id=opportunity.id, measure_code="realised_savings")
    await db_session.execute(
        sa.text(
            "UPDATE opportunities SET annual_financial_impact_current_event_id = :afi_ev, "
            "realised_savings_current_event_id = :rs_ev WHERE id = :oid"
        ),
        {"afi_ev": afi_event_id, "rs_ev": rs_event_id, "oid": opportunity.id},
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
        event_id = expected_amount_event_id

    return Seed()
