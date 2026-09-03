"""
P-03 migration-compatibility verification. Proves migration 0021 correctly transitions a REAL,
pre-existing (0020-shaped) database - not just an empty one. Run only in the dedicated CI
migration-compatibility job's own disposable PostgreSQL service - never against a shared,
persistent, or development database.

Mandatory rule: the 0020 seed stage uses raw SQL only. The current P-03 ORM models (RebatePeriodActual,
Opportunity, FinancialAmountStatusEvent, ...) describe the POST-0021 schema shape and are never
instantiated while the database is at revision 0020 - every column named in seed_0020_shaped_rows()
was verified directly against migrations 0002, 0005, and 0009 (the only migrations that shaped
these two tables before 0021) before this script was written, not assumed from the current model.

Exits non-zero on any failed assertion - this is what CI reads as pass/fail, not test output
parsing.
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

import psycopg
from alembic import command
from alembic.config import Config


def _dsn() -> str:
    url = os.environ["DATABASE_URL_SYNC"]
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _alembic_config() -> Config:
    return Config("alembic.ini")


def seed_0020_shaped_rows(conn: psycopg.Connection) -> dict:
    """
    Raw SQL only. Every column named below exists at revision 0020 - confirmed directly against
    migrations 0002 (opportunities creation), 0005 (rebate_period_actuals creation), and 0009
    (opportunities Phase 5 additions, including realised_savings) before this was written.
    """
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO organisations (name, default_currency, country) VALUES (%s, %s, %s) RETURNING id",
        ("Migration Compat Test Org", "ZAR", "ZA"),
    )
    org_id = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO users (first_name, last_name, email, password_hash, verified) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        ("Migration", "Compat", "migration-compat@procureiq.local", "not-a-real-hash-test-only", True),
    )
    user_id = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO organisation_memberships (user_id, organisation_id, role, status) "
        "VALUES (%s, %s, %s, %s)",
        (user_id, org_id, "owner", "active"),
    )

    cur.execute(
        "INSERT INTO rebate_agreements (organisation_id, title, rebate_type, period_type, "
        "flat_rate_pct, currency, created_by_user_id) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (org_id, "Migration Compat Agreement", "fixed_percentage", "quarterly", "0.02", "ZAR", user_id),
    )
    agreement_id = cur.fetchone()[0]

    # expected_amount NULL - the "not yet calculated" case
    cur.execute(
        "INSERT INTO rebate_period_actuals (organisation_id, rebate_agreement_id, period_start, "
        "period_end, entry_source, entered_by_user_id, expected_amount) "
        "VALUES (%s, %s, '2026-01-01', '2026-03-31', 'manual', %s, NULL) RETURNING id",
        (org_id, agreement_id, user_id),
    )
    rpa_null_id = cur.fetchone()[0]

    # expected_amount non-NULL - the "legacy_unverified" case
    cur.execute(
        "INSERT INTO rebate_period_actuals (organisation_id, rebate_agreement_id, period_start, "
        "period_end, entry_source, entered_by_user_id, expected_amount) "
        "VALUES (%s, %s, '2026-04-01', '2026-06-30', 'manual', %s, 12345.6700) RETURNING id",
        (org_id, agreement_id, user_id),
    )
    rpa_nonnull_id = cur.fetchone()[0]

    # annual_financial_impact NULL, realised_savings NULL - both-unknown baseline
    cur.execute(
        "INSERT INTO opportunities (organisation_id, title, opportunity_type, status, "
        "created_by_user_id, annual_financial_impact, realised_savings) "
        "VALUES (%s, %s, %s, %s, %s, NULL, NULL) RETURNING id",
        (org_id, "Opp AFI Null RS Null", "price_increase_challenge", "identified", user_id),
    )
    opp_both_null_id = cur.fetchone()[0]

    # annual_financial_impact non-NULL, realised_savings NULL
    cur.execute(
        "INSERT INTO opportunities (organisation_id, title, opportunity_type, status, "
        "created_by_user_id, annual_financial_impact, realised_savings) "
        "VALUES (%s, %s, %s, %s, %s, 8800.0000, NULL) RETURNING id",
        (org_id, "Opp AFI NonNull RS Null", "price_increase_challenge", "identified", user_id),
    )
    opp_afi_nonnull_id = cur.fetchone()[0]

    # annual_financial_impact NULL, realised_savings non-NULL
    cur.execute(
        "INSERT INTO opportunities (organisation_id, title, opportunity_type, status, "
        "created_by_user_id, annual_financial_impact, realised_savings) "
        "VALUES (%s, %s, %s, %s, %s, NULL, 4400.5000) RETURNING id",
        (org_id, "Opp AFI Null RS NonNull", "realised", user_id),
    )
    opp_rs_nonnull_id = cur.fetchone()[0]

    conn.commit()
    return {
        "org_id": org_id, "user_id": user_id, "agreement_id": agreement_id,
        "rpa_null_id": rpa_null_id, "rpa_nonnull_id": rpa_nonnull_id,
        "opp_both_null_id": opp_both_null_id, "opp_afi_nonnull_id": opp_afi_nonnull_id,
        "opp_rs_nonnull_id": opp_rs_nonnull_id,
        "rpa_nonnull_original_amount": Decimal("12345.6700"),
        "opp_afi_nonnull_original_amount": Decimal("8800.0000"),
        "opp_rs_nonnull_original_amount": Decimal("4400.5000"),
    }


def verify_post_0021_state(conn: psycopg.Connection, seed: dict) -> list[str]:
    """Returns a list of failure descriptions - empty means everything passed."""
    failures: list[str] = []
    cur = conn.cursor()

    def check(condition: bool, description: str) -> None:
        if not condition:
            failures.append(description)

    # --- expected_amount NULL row -> unknown ---
    cur.execute(
        "SELECT expected_amount, expected_amount_status, expected_amount_current_event_id "
        "FROM rebate_period_actuals WHERE id = %s",
        (seed["rpa_null_id"],),
    )
    amount, status, event_id = cur.fetchone()
    check(amount is None, f"rpa_null_id: expected_amount should remain NULL, got {amount!r}")
    check(status == "unknown", f"rpa_null_id: expected status='unknown', got {status!r}")
    check(event_id is not None, "rpa_null_id: expected_amount_current_event_id must not be NULL")

    # --- expected_amount non-NULL row -> legacy_unverified, value UNCHANGED ---
    cur.execute(
        "SELECT expected_amount, expected_amount_status, expected_amount_current_event_id "
        "FROM rebate_period_actuals WHERE id = %s",
        (seed["rpa_nonnull_id"],),
    )
    amount, status, event_id = cur.fetchone()
    check(
        amount == seed["rpa_nonnull_original_amount"],
        f"rpa_nonnull_id: amount changed - was {seed['rpa_nonnull_original_amount']}, now {amount!r}",
    )
    check(status == "legacy_unverified", f"rpa_nonnull_id: expected 'legacy_unverified', got {status!r}")
    check(event_id is not None, "rpa_nonnull_id: expected_amount_current_event_id must not be NULL")

    # --- genesis event correctness for both rebate rows ---
    for label, rpa_id, expected_status, expected_amount in (
        ("rpa_null", seed["rpa_null_id"], "unknown", None),
        ("rpa_nonnull", seed["rpa_nonnull_id"], "legacy_unverified", seed["rpa_nonnull_original_amount"]),
    ):
        cur.execute(
            "SELECT ev.new_status, ev.new_amount, ev.event_version, ev.old_status "
            "FROM financial_amount_status_events ev "
            "JOIN rebate_period_actuals rpa ON rpa.expected_amount_current_event_id = ev.id "
            "WHERE rpa.id = %s",
            (rpa_id,),
        )
        row = cur.fetchone()
        check(row is not None, f"{label}: no genesis event found via the current_event_id pointer")
        if row:
            new_status, new_amount, version, old_status = row
            check(version == 1, f"{label}: genesis event should be version 1, got {version}")
            check(old_status is None, f"{label}: genesis event's old_status should be NULL, got {old_status!r}")
            check(new_status == expected_status, f"{label}: event new_status={new_status!r}, expected {expected_status!r}")
            check(new_amount == expected_amount, f"{label}: event new_amount={new_amount!r}, expected {expected_amount!r}")

    # --- opportunities: both measures, both null/non-null cases ---
    cur.execute(
        "SELECT annual_financial_impact, annual_financial_impact_status, annual_financial_impact_current_event_id, "
        "realised_savings, realised_savings_status, realised_savings_current_event_id "
        "FROM opportunities WHERE id = %s",
        (seed["opp_both_null_id"],),
    )
    afi_amt, afi_status, afi_ev, rs_amt, rs_status, rs_ev = cur.fetchone()
    check(afi_amt is None and afi_status == "unknown" and afi_ev is not None,
          f"opp_both_null: annual_financial_impact side wrong - amount={afi_amt!r} status={afi_status!r} event={afi_ev!r}")
    check(rs_amt is None and rs_status == "unknown" and rs_ev is not None,
          f"opp_both_null: realised_savings side wrong - amount={rs_amt!r} status={rs_status!r} event={rs_ev!r}")

    cur.execute(
        "SELECT annual_financial_impact, annual_financial_impact_status FROM opportunities WHERE id = %s",
        (seed["opp_afi_nonnull_id"],),
    )
    afi_amt, afi_status = cur.fetchone()
    check(afi_amt == seed["opp_afi_nonnull_original_amount"],
          f"opp_afi_nonnull: amount changed - was {seed['opp_afi_nonnull_original_amount']}, now {afi_amt!r}")
    check(afi_status == "legacy_unverified", f"opp_afi_nonnull: expected 'legacy_unverified', got {afi_status!r}")

    cur.execute(
        "SELECT realised_savings, realised_savings_status FROM opportunities WHERE id = %s",
        (seed["opp_rs_nonnull_id"],),
    )
    rs_amt, rs_status = cur.fetchone()
    check(rs_amt == seed["opp_rs_nonnull_original_amount"],
          f"opp_rs_nonnull: amount changed - was {seed['opp_rs_nonnull_original_amount']}, now {rs_amt!r}")
    check(rs_status == "legacy_unverified", f"opp_rs_nonnull: expected 'legacy_unverified', got {rs_status!r}")

    # --- genesis event correctness for BOTH opportunity measures - was missing, added: the
    # rebate-side equivalent check above must not be the only place this gets proven ---
    for label, opp_id, measure_code, pointer_col, expected_status, expected_amount in (
        ("opp_both_null.afi", seed["opp_both_null_id"], "annual_financial_impact",
         "annual_financial_impact_current_event_id", "unknown", None),
        ("opp_both_null.rs", seed["opp_both_null_id"], "realised_savings",
         "realised_savings_current_event_id", "unknown", None),
        ("opp_afi_nonnull.afi", seed["opp_afi_nonnull_id"], "annual_financial_impact",
         "annual_financial_impact_current_event_id", "legacy_unverified", seed["opp_afi_nonnull_original_amount"]),
        ("opp_rs_nonnull.rs", seed["opp_rs_nonnull_id"], "realised_savings",
         "realised_savings_current_event_id", "legacy_unverified", seed["opp_rs_nonnull_original_amount"]),
    ):
        cur.execute(
            f"SELECT ev.new_status, ev.new_amount, ev.event_version, ev.old_status, ev.measure_code "
            f"FROM financial_amount_status_events ev "
            f"JOIN opportunities o ON o.{pointer_col} = ev.id "
            f"WHERE o.id = %s",
            (opp_id,),
        )
        row = cur.fetchone()
        check(row is not None, f"{label}: no genesis event found via the current_event_id pointer")
        if row:
            new_status, new_amount, version, old_status, measure_code_found = row
            check(version == 1, f"{label}: genesis event should be version 1, got {version}")
            check(old_status is None, f"{label}: genesis event's old_status should be NULL, got {old_status!r}")
            check(measure_code_found == measure_code, f"{label}: event measure_code={measure_code_found!r}, expected {measure_code!r}")
            check(new_status == expected_status, f"{label}: event new_status={new_status!r}, expected {expected_status!r}")
            check(new_amount == expected_amount, f"{label}: event new_amount={new_amount!r}, expected {expected_amount!r}")

    # --- no row anywhere left without its required pointer ---
    cur.execute("SELECT COUNT(*) FROM rebate_period_actuals WHERE expected_amount_current_event_id IS NULL")
    check(cur.fetchone()[0] == 0, "at least one rebate_period_actuals row has a NULL current_event_id pointer")
    cur.execute(
        "SELECT COUNT(*) FROM opportunities WHERE annual_financial_impact_current_event_id IS NULL "
        "OR realised_savings_current_event_id IS NULL"
    )
    check(cur.fetchone()[0] == 0, "at least one opportunities row has a NULL current_event_id pointer")

    return failures


def verify_rollback(conn: psycopg.Connection, seed: dict) -> list[str]:
    """Mechanical downgrade check only - confirms 0021's downgrade() runs cleanly against this
    seeded, non-live dataset and that amount columns survive untouched. Not a claim that
    downgrade is safe against real, live-captured provenance - see the P-03 handover's own
    explicit caveat on that point."""
    failures: list[str] = []
    cur = conn.cursor()
    cur.execute("SELECT expected_amount FROM rebate_period_actuals WHERE id = %s", (seed["rpa_nonnull_id"],))
    amount = cur.fetchone()[0]
    if amount != seed["rpa_nonnull_original_amount"]:
        failures.append(f"post-downgrade: rpa_nonnull amount changed - now {amount!r}")

    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'rebate_period_actuals' AND column_name = 'expected_amount_status'"
    )
    if cur.fetchone() is not None:
        failures.append("post-downgrade: expected_amount_status column still exists, should be dropped")

    cur.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name = 'financial_amount_status_events'"
    )
    if cur.fetchone() is not None:
        failures.append("post-downgrade: financial_amount_status_events table still exists, should be dropped")

    return failures


def main() -> int:
    print("=== Step 1: alembic upgrade 0020 (already run as a separate CI step) ===")

    print("=== Step 2: seed 0020-shaped rows via raw SQL only ===")
    conn = psycopg.connect(_dsn())
    try:
        seed = seed_0020_shaped_rows(conn)
        print(f"Seeded: {seed}")
    finally:
        conn.close()

    print("=== Step 3: alembic upgrade 0021 ===")
    command.upgrade(_alembic_config(), "0021")

    print("=== Step 4: verify backfill, genesis events, pointers ===")
    conn = psycopg.connect(_dsn())
    try:
        failures = verify_post_0021_state(conn, seed)
    finally:
        conn.close()

    if failures:
        print(f"FAILED - {len(failures)} assertion(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All post-0021 assertions passed.")

    print("=== Step 5: alembic downgrade 0020 (mechanical check only) ===")
    command.downgrade(_alembic_config(), "0020")

    conn = psycopg.connect(_dsn())
    try:
        rollback_failures = verify_rollback(conn, seed)
    finally:
        conn.close()

    if rollback_failures:
        print(f"ROLLBACK CHECK FAILED - {len(rollback_failures)} assertion(s):")
        for f in rollback_failures:
            print(f"  - {f}")
        return 1
    print("Rollback check passed - amount columns survived, P-03 schema cleanly removed.")

    print("=== ALL CHECKS PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
