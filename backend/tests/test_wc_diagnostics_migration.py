"""
WC-DERIVED-METRIC-DIAGNOSTICS-R1: focused migration tests for 0025
(working_capital_snapshots.derived_metric_diagnostics).

Uses its own disposable database (drop/create + real `alembic upgrade`/`downgrade` subprocess
calls, same pattern as conftest.py's own _prepare_schema) rather than the shared procureiq_test
database every other test file depends on - this test deliberately moves the schema backward and
forward across a single revision boundary, which would corrupt the shared session-scoped
database's state for every other test in the same pytest run if it happened there.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from app.core.config import get_settings

_DB_NAME = "procureiq_test_wc_migration_0025"


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
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (_DB_NAME,),
            )
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(_DB_NAME)))


@pytest.fixture
def wc_migration_db():
    """Fresh, disposable database - dropped before creation and dropped again on teardown
    regardless of test outcome. Never touches the shared procureiq_test database."""
    admin_dsn = _admin_maintenance_dsn()
    _terminate_and_drop(admin_dsn)
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(_DB_NAME)))

    target_async = get_settings().database_url.rsplit("/", 1)[0] + f"/{_DB_NAME}"
    target_sync = get_settings().database_url_sync.rsplit("/", 1)[0] + f"/{_DB_NAME}"
    try:
        yield target_async, target_sync
    finally:
        _terminate_and_drop(admin_dsn)


def test_upgrade_from_0024_preserves_legacy_row_and_downgrade_is_reversible(wc_migration_db):
    target_async, target_sync = wc_migration_db
    plain_dsn = target_sync.replace("postgresql+psycopg://", "postgresql://", 1)

    # Migrate only as far as the revision immediately before this phase's new one.
    _run_alembic("upgrade", "0024", database_url=target_async, database_url_sync=target_sync)

    with psycopg.connect(plain_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            # Confirm the new column genuinely does not exist yet at 0024.
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'working_capital_snapshots' AND column_name = 'derived_metric_diagnostics'"
            )
            assert cur.fetchone() is None

            # Seed one legacy row directly, pre-migration - real FK rows first.
            cur.execute(
                "INSERT INTO organisations (public_id, name, default_currency, country) "
                "VALUES (gen_random_uuid(), 'WC Migration Org', 'ZAR', 'ZA') RETURNING id"
            )
            org_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO users (public_id, first_name, last_name, email, password_hash, verified) "
                "VALUES (gen_random_uuid(), 'WC', 'Migration', %s, 'not-a-real-hash', true) RETURNING id",
                (f"wc-migration-{uuid.uuid4()}@procureiq.local",),
            )
            user_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO working_capital_snapshots (public_id, organisation_id, as_of_date, "
                "accounts_receivable, accounts_payable, inventory_value, annualized_revenue, "
                "annualized_cogs, uploaded_by_user_id) "
                "VALUES (gen_random_uuid(), %s, '2026-01-31', 100000, 50000, 30000, 1000000, 700000, %s) "
                "RETURNING id",
                (org_id, user_id),
            )
            legacy_row_id = cur.fetchone()[0]

    # Required test #1: upgrade from the prior revision to the new head succeeds.
    _run_alembic("upgrade", "head", database_url=target_async, database_url_sync=target_sync)

    with psycopg.connect(plain_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'working_capital_snapshots' AND column_name = 'derived_metric_diagnostics'"
            )
            row = cur.fetchone()
            assert row is not None, "derived_metric_diagnostics column was not created"
            assert row[0] == "YES"  # nullable, no server default per the phase's own requirement

            # Required test #2: the pre-existing row was not rewritten - NULL (unknown), not [].
            cur.execute(
                "SELECT derived_metric_diagnostics, accounts_receivable "
                "FROM working_capital_snapshots WHERE id = %s",
                (legacy_row_id,),
            )
            diagnostics, ar = cur.fetchone()
            assert diagnostics is None
            assert ar == 100000  # raw fact untouched by the migration

    # Required test #10: downgrade is structurally reversible - removes only this column.
    _run_alembic("downgrade", "0024", database_url=target_async, database_url_sync=target_sync)
    with psycopg.connect(plain_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'working_capital_snapshots' AND column_name = 'derived_metric_diagnostics'"
            )
            assert cur.fetchone() is None
            cur.execute(
                "SELECT accounts_receivable FROM working_capital_snapshots WHERE id = %s", (legacy_row_id,)
            )
            assert cur.fetchone()[0] == 100000  # every other column survives downgrade untouched
