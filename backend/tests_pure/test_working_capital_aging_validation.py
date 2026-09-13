"""
Pure-logic tests for the working capital / aging ingestion validators. Written before the
implementation, per this sprint's test-first sequence. The service layer's period-locking logic
(ConflictError on re-ingest, corrects_id on is_correction=True) needs a real DB session and is
covered by tests/test_working_capital_ingestion.py instead - not duplicated here.
"""
from __future__ import annotations

import unittest

from app.ingestion.aging_validation import validate_aging_rows
from app.ingestion.validation import IssueSeverity
from app.ingestion.working_capital_validation import validate_working_capital_row


class TestWorkingCapitalRowValidation(unittest.TestCase):
    def _valid_row(self, **overrides):
        row = {
            "as_of_date": "2026-08-31", "accounts_receivable": "31596977.24",
            "accounts_payable": "23532821.46", "inventory_value": "21895070.82",
            "cash_balance": "-19518395.79", "annualized_revenue": "355848477.03",
            "annualized_cogs": "290075966.07",
        }
        row.update(overrides)
        return row

    def test_valid_row_with_real_gourmet_figures_passes(self):
        result = validate_working_capital_row(self._valid_row())
        self.assertTrue(result["is_valid"])
        self.assertEqual(result["issues"], [])

    def test_negative_cash_is_not_flagged_at_all_not_even_a_warning(self):
        # The real Gourmet figure IS negative (an overdraft) - this must never be flagged, not
        # even as a warning, since it's not unusual data, it's the actual documented state.
        result = validate_working_capital_row(self._valid_row(cash_balance="-19518395.79"))
        cash_issues = [i for i in result["issues"] if i.field == "cash_balance"]
        self.assertEqual(cash_issues, [])

    def test_missing_cash_balance_is_valid_not_an_error(self):
        row = self._valid_row()
        del row["cash_balance"]
        result = validate_working_capital_row(row)
        self.assertTrue(result["is_valid"])

    def test_negative_accounts_receivable_is_a_warning_not_an_error(self):
        result = validate_working_capital_row(self._valid_row(accounts_receivable="-5000"))
        issues = [i for i in result["issues"] if i.field == "accounts_receivable"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, IssueSeverity.WARNING)
        self.assertTrue(result["is_valid"])  # a warning never blocks ingestion

    def test_negative_inventory_value_is_an_error_not_a_warning(self):
        # Unlike AR/AP/cash, there is no real-world state where inventory value is legitimately
        # negative - this is a data-quality error, not an unusual-but-real figure.
        result = validate_working_capital_row(self._valid_row(inventory_value="-100"))
        issues = [i for i in result["issues"] if i.field == "inventory_value"]
        self.assertEqual(issues[0].severity, IssueSeverity.ERROR)
        self.assertFalse(result["is_valid"])

    def test_zero_annualized_revenue_and_cogs_are_valid_not_flagged(self):
        # calculate_working_capital_metrics already returns None gracefully for this case - not
        # re-flagged as a data problem at ingestion.
        result = validate_working_capital_row(self._valid_row(annualized_revenue="0", annualized_cogs="0"))
        self.assertTrue(result["is_valid"])

    def test_missing_as_of_date_is_an_error(self):
        row = self._valid_row()
        del row["as_of_date"]
        result = validate_working_capital_row(row)
        self.assertFalse(result["is_valid"])

    def test_malformed_date_is_an_error(self):
        result = validate_working_capital_row(self._valid_row(as_of_date="31/08/2026"))
        self.assertFalse(result["is_valid"])

    def test_malformed_numeric_field_is_an_error(self):
        result = validate_working_capital_row(self._valid_row(accounts_receivable="not-a-number"))
        self.assertFalse(result["is_valid"])


class TestAgingRowValidation(unittest.TestCase):
    def test_valid_rows_pass(self):
        rows = [{"amount": "200000", "days_overdue": "10"}, {"amount": "150000", "days_overdue": "35"}]
        results = validate_aging_rows(rows)
        self.assertTrue(all(r["is_valid"] for r in results))

    def test_negative_days_overdue_is_valid_not_an_error(self):
        # A not-yet-due invoice can reasonably have a negative days_overdue - classify_aging_buckets's
        # own boundary (days < 30 -> current) already handles this correctly without needing it
        # rejected at ingestion.
        results = validate_aging_rows([{"amount": "1000", "days_overdue": "-5"}])
        self.assertTrue(results[0]["is_valid"])

    def test_missing_amount_is_an_error(self):
        results = validate_aging_rows([{"days_overdue": "10"}])
        self.assertFalse(results[0]["is_valid"])

    def test_malformed_days_overdue_is_an_error(self):
        results = validate_aging_rows([{"amount": "1000", "days_overdue": "not-a-number"}])
        self.assertFalse(results[0]["is_valid"])

    def test_empty_input_returns_empty_list_not_error(self):
        self.assertEqual(validate_aging_rows([]), [])


if __name__ == "__main__":
    unittest.main()
