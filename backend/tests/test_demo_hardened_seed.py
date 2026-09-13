"""D-01: proves app/db/seeds/demo_hardened_seed.py's idempotency claim directly - calling it
twice must reuse the same organisation and user, never create a second of either. Written, not
executed here - same pre-existing sandbox gap as every DB-dependent test this engagement
(pydantic-settings missing, no live Postgres)."""
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest_asyncio
from psycopg import sql
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models import (
    AgingLedgerSnapshot,
    CostAllocationRule,
    CostToServeLedger,
    Organisation,
    OrganisationMembership,
    User,
)
from app.db.seeds.demo_hardened_seed import DEMO_LOGIN_EMAIL, seed_demo_hardened
from app.db.seeds.management_accounting_demo import DEMO_ORG_NAME


async def test_seed_run_twice_produces_no_duplicate_organisation_or_user(db_session):
    os.environ["DEMO_USER_PASSWORD"] = "test-only-password-for-this-run"
    try:
        first = await seed_demo_hardened(db_session)
        second = await seed_demo_hardened(db_session)
    finally:
        del os.environ["DEMO_USER_PASSWORD"]

    assert first["organisation_public_id"] == second["organisation_public_id"]
    assert second["user_status"].startswith("reused")
    assert second["demo_data_status"].startswith("reused")

    org_count = await db_session.execute(
        select(func.count()).select_from(Organisation).where(Organisation.name == DEMO_ORG_NAME)
    )
    assert org_count.scalar_one() == 1

    user_count = await db_session.execute(
        select(func.count()).select_from(User).where(User.email == DEMO_LOGIN_EMAIL)
    )
    assert user_count.scalar_one() == 1


async def test_seed_without_demo_user_password_fails_clearly(db_session):
    os.environ.pop("DEMO_USER_PASSWORD", None)  # ensure genuinely absent, not just falsy
    try:
        raised = False
        try:
            await seed_demo_hardened(db_session)
        except RuntimeError as e:
            raised = True
            assert "DEMO_USER_PASSWORD" in str(e)
        assert raised, "expected a clear RuntimeError when DEMO_USER_PASSWORD is unset"
    finally:
        pass


_DB_NAME = "procureiq_test_demo_hardened_seed"


def _admin_maintenance_dsn() -> str:
    plain = get_settings().database_url_sync.replace("postgresql+psycopg://", "postgresql://", 1)
    prefix, _, _ = plain.rpartition("/")
    return f"{prefix}/postgres"


def _run_alembic(*args: str, database_url: str, database_url_sync: str) -> None:
    backend_root = Path(__file__).resolve().parent.parent
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=backend_root,
        env={**os.environ, "DATABASE_URL": database_url, "DATABASE_URL_SYNC": database_url_sync},
        check=True,
    )


def _terminate_and_drop(admin_dsn: str) -> None:
    with psycopg.connect(admin_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (_DB_NAME,),
        )
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(_DB_NAME)))


@pytest_asyncio.fixture
async def demo_hardened_seed_db():
    """BACKEND-RUFF-F841-FIX-R1: a dedicated, disposable database - dropped before creation and
    dropped again on teardown, migrated to head fresh - never the shared, session-scoped
    procureiq_test database every other test in this file (and tests/api/test_canvas_management_demo.py)
    depends on. seed_demo_hardened's "created" path (the exact branch containing the reviewed
    `await seed_management_accounting_demo(db)` call this phase renames the binding for) only
    runs when DEMO_ORG_NAME is genuinely absent - the shared database cannot prove that, since
    other test modules seed that identical org name there directly. Same disposable-database
    pattern as tests/test_wc_diagnostics_migration.py's own wc_migration_db fixture."""
    admin_dsn = _admin_maintenance_dsn()
    _terminate_and_drop(admin_dsn)
    with psycopg.connect(admin_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(_DB_NAME)))

    target_async = get_settings().database_url.rsplit("/", 1)[0] + f"/{_DB_NAME}"
    target_sync = get_settings().database_url_sync.rsplit("/", 1)[0] + f"/{_DB_NAME}"
    _run_alembic("upgrade", "head", database_url=target_async, database_url_sync=target_sync)

    engine = create_async_engine(target_async)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()
        _terminate_and_drop(admin_dsn)


async def test_seed_demo_hardened_creates_organisation_user_membership_and_demo_financial_rows(
    demo_hardened_seed_db,
):
    """Proof-first test for BACKEND-RUFF-F841-FIX-R1: exercises the exact `if organisation is
    None:` branch - and therefore the exact `await seed_management_accounting_demo(db)` call
    whose discarded return-value binding this phase renames to `_` - against a database
    guaranteed to have no pre-existing demo organisation, then verifies every persisted side
    effect both that call and the rest of seed_demo_hardened are responsible for. Must pass
    identically before and after the binding rename, since the rename changes nothing about
    what is awaited, evaluated, or persisted."""
    db = demo_hardened_seed_db
    os.environ["DEMO_USER_PASSWORD"] = "test-only-password-for-this-run"
    try:
        result = await seed_demo_hardened(db)
    finally:
        del os.environ["DEMO_USER_PASSWORD"]

    assert result["demo_data_status"] == "created"
    assert result["user_status"] == "created"

    org_result = await db.execute(select(Organisation).where(Organisation.name == DEMO_ORG_NAME))
    organisation = org_result.scalar_one()
    assert str(organisation.public_id) == result["organisation_public_id"]

    user_result = await db.execute(select(User).where(User.email == DEMO_LOGIN_EMAIL))
    user = user_result.scalar_one()

    membership_count = await db.execute(
        select(func.count()).select_from(OrganisationMembership)
        .where(OrganisationMembership.user_id == user.id)
        .where(OrganisationMembership.organisation_id == organisation.id)
    )
    assert membership_count.scalar_one() == 1

    rule_count = await db.execute(
        select(func.count()).select_from(CostAllocationRule)
        .where(CostAllocationRule.organisation_id == organisation.id)
    )
    assert rule_count.scalar_one() > 0

    ledger_count = await db.execute(
        select(func.count()).select_from(CostToServeLedger)
        .where(CostToServeLedger.organisation_id == organisation.id)
    )
    assert ledger_count.scalar_one() > 0

    aging_count = await db.execute(
        select(func.count()).select_from(AgingLedgerSnapshot)
        .where(AgingLedgerSnapshot.organisation_id == organisation.id)
    )
    assert aging_count.scalar_one() > 0
