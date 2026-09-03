"""Covers notice-period math, status classification, renewal-date computation, alert due-dates,
and escalation calculations (including the ADR-009 fabrication guardrail) for the contract
lifecycle engine."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from app.analytics.contract_calculations import (
    ContractStatus,
    EscalationType,
    TieredEscalationBand,
    calculate_escalated_price,
    calculate_next_renewal_date,
    calculate_notice_deadline,
    calculate_tiered_escalated_price,
    classify_contract_status,
    determine_due_alerts,
    is_notice_window_open,
)


class TestNoticeDeadline(unittest.TestCase):
    def test_notice_deadline_worked_example(self):
        # A contract expiring 2026-12-31 with 90 days notice: last day to give notice is 2026-10-02.
        deadline = calculate_notice_deadline(date(2026, 12, 31), 90)
        self.assertEqual(deadline, date(2026, 10, 2))

    def test_negative_notice_period_rejected(self):
        with self.assertRaises(ValueError):
            calculate_notice_deadline(date(2026, 12, 31), -10)

    def test_notice_window_open_before_deadline(self):
        deadline = calculate_notice_deadline(date(2026, 12, 31), 90)
        self.assertTrue(is_notice_window_open(date(2026, 9, 1), deadline, date(2026, 12, 31)))

    def test_notice_window_closed_after_deadline(self):
        deadline = calculate_notice_deadline(date(2026, 12, 31), 90)
        self.assertFalse(is_notice_window_open(date(2026, 11, 1), deadline, date(2026, 12, 31)))


class TestRenewalDate(unittest.TestCase):
    def test_no_renewal_when_auto_renew_false(self):
        result = calculate_next_renewal_date(date(2026, 12, 31), auto_renew=False, renewal_term_months=12)
        self.assertIsNone(result)

    def test_auto_renew_requires_term_months(self):
        with self.assertRaises(ValueError):
            calculate_next_renewal_date(date(2026, 12, 31), auto_renew=True, renewal_term_months=None)

    def test_renewal_date_adds_months_correctly(self):
        result = calculate_next_renewal_date(date(2026, 12, 31), auto_renew=True, renewal_term_months=12)
        self.assertEqual(result, date(2027, 12, 31))

    def test_renewal_date_clamps_day_for_short_month(self):
        # 31 Jan + 1 month must not crash - clamps to the last valid day of February.
        result = calculate_next_renewal_date(date(2026, 1, 31), auto_renew=True, renewal_term_months=1)
        self.assertEqual(result, date(2026, 2, 28))


class TestStatusClassification(unittest.TestCase):
    def setUp(self):
        self.expiry = date(2026, 12, 31)
        # Deliberately shorter than the 90-day expiring_soon threshold, so the two states are
        # actually distinguishable in these tests - a 90-day notice period on a 90-day threshold
        # means the contract jumps straight from ACTIVE to NOTICE_PERIOD_OPEN with no window in
        # between, which was the bug in the first version of this test file (it asserted
        # EXPIRING_SOON using dates that could never produce it given a 90/90 setup).
        self.notice_period_days = 30
        self.deadline = calculate_notice_deadline(self.expiry, self.notice_period_days)  # 2026-12-01

    def test_active_well_before_expiry(self):
        status = classify_contract_status(date(2026, 6, 1), self.expiry, self.deadline, auto_renew=False)
        self.assertEqual(status, ContractStatus.ACTIVE)

    def test_expiring_soon_within_default_threshold(self):
        # 77 days out: inside the 90-day expiring_soon threshold, but before the 30-day notice
        # deadline (2026-12-01) - the window this state exists to represent.
        status = classify_contract_status(date(2026, 10, 15), self.expiry, self.deadline, auto_renew=False)
        self.assertEqual(status, ContractStatus.EXPIRING_SOON)

    def test_notice_period_open_status_after_deadline_no_auto_renew(self):
        status = classify_contract_status(date(2026, 12, 15), self.expiry, self.deadline, auto_renew=False)
        self.assertEqual(status, ContractStatus.NOTICE_PERIOD_OPEN)

    def test_auto_renewing_status_after_deadline_with_auto_renew(self):
        status = classify_contract_status(date(2026, 12, 15), self.expiry, self.deadline, auto_renew=True)
        self.assertEqual(status, ContractStatus.AUTO_RENEWING)

    def test_expired_after_expiry_date(self):
        status = classify_contract_status(date(2027, 1, 15), self.expiry, self.deadline, auto_renew=False)
        self.assertEqual(status, ContractStatus.EXPIRED)


class TestDueAlerts(unittest.TestCase):
    def test_alerts_fire_for_every_crossed_unfired_threshold(self):
        # Deliberate design choice, not a bug: if a contract is added to the system (or the
        # engine simply hasn't run) until it's already 60 days out, it should surface every
        # milestone the user hasn't been told about yet (180, 90, AND 60 day), not just the
        # nearest one - otherwise a contract discovered late silently skips the earlier warnings
        # instead of catching the user up on all of them.
        expiry = date(2026, 12, 31)
        deadline = calculate_notice_deadline(expiry, 30)
        today = expiry - __import__("datetime").timedelta(days=60)  # exactly 60 days out
        due = determine_due_alerts(today, expiry, deadline, already_fired=set())
        self.assertEqual(set(due), {"expiry_180", "expiry_90", "expiry_60"})
        self.assertNotIn("expiry_30", due)  # not yet within 30 days

    def test_already_fired_alerts_are_not_repeated(self):
        expiry = date(2026, 12, 31)
        deadline = calculate_notice_deadline(expiry, 30)
        today = expiry - __import__("datetime").timedelta(days=60)
        due = determine_due_alerts(
            today, expiry, deadline, already_fired={"expiry_180", "expiry_90", "expiry_60"}
        )
        self.assertEqual(due, [])

    def test_notice_deadline_alert_fires_exactly_on_deadline_day(self):
        expiry = date(2026, 12, 31)
        deadline = calculate_notice_deadline(expiry, 30)  # 2026-12-01
        due = determine_due_alerts(deadline, expiry, deadline, already_fired=set())
        self.assertIn("notice_deadline", due)


class TestEscalation(unittest.TestCase):
    def test_no_escalation_returns_base_price(self):
        result = calculate_escalated_price(Decimal("100"), EscalationType.NONE)
        self.assertEqual(result, Decimal("100.0000"))

    def test_fixed_percentage_escalation(self):
        result = calculate_escalated_price(
            Decimal("100"), EscalationType.FIXED_PERCENTAGE, escalation_rate_pct=Decimal("0.05")
        )
        self.assertEqual(result, Decimal("105.0000"))

    def test_fixed_percentage_compounds_over_multiple_periods(self):
        result = calculate_escalated_price(
            Decimal("100"), EscalationType.FIXED_PERCENTAGE,
            escalation_rate_pct=Decimal("0.05"), periods_elapsed=2,
        )
        self.assertEqual(result, Decimal("110.2500"))  # 100 * 1.05^2, not 100 * 1.10

    def test_fixed_percentage_without_rate_raises(self):
        with self.assertRaises(ValueError):
            calculate_escalated_price(Decimal("100"), EscalationType.FIXED_PERCENTAGE)

    def test_cpi_linked_without_index_value_raises(self):
        # The exact guardrail ADR-009 exists for - must never silently default.
        with self.assertRaises(ValueError):
            calculate_escalated_price(Decimal("100"), EscalationType.CPI_LINKED)

    def test_cpi_linked_with_supplied_index_value_calculates(self):
        result = calculate_escalated_price(
            Decimal("100"), EscalationType.CPI_LINKED, external_index_value_pct=Decimal("0.045")
        )
        self.assertEqual(result, Decimal("104.5000"))

    def test_tiered_escalation_or_negotiated_rejected_by_single_formula_function(self):
        with self.assertRaises(ValueError):
            calculate_escalated_price(Decimal("100"), EscalationType.TIERED)


class TestTieredEscalation(unittest.TestCase):
    def test_applies_highest_reached_band(self):
        bands = [
            TieredEscalationBand(Decimal("0"), Decimal("0.02")),
            TieredEscalationBand(Decimal("1000000"), Decimal("0.04")),
            TieredEscalationBand(Decimal("5000000"), Decimal("0.06")),
        ]
        result = calculate_tiered_escalated_price(Decimal("100"), Decimal("2500000"), bands)
        self.assertEqual(result, Decimal("104.0000"))  # 4% band, not 2% or 6%

    def test_no_bands_raises(self):
        with self.assertRaises(ValueError):
            calculate_tiered_escalated_price(Decimal("100"), Decimal("500"), [])


if __name__ == "__main__":
    unittest.main()
