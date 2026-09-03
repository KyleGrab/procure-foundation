"""
End-to-end ADR-004 pipeline test: raw AI extraction -> unverified staging record -> assert
blocked from the calculation engine -> simulated human verification -> promoted fields -> fed
into the real deterministic calculation engine -> confirm correct alerts/deadlines/renewal dates.

Every step calls real production code, not a re-implementation for the test's sake:
- app.ai.extraction_guardrails (the actual ADR-004 gate, also used by
  app.services.contract_service.promote_extraction_fields)
- app.analytics.contract_calculations (the actual deterministic engine, also used by the service
  layer and proven separately in test_contract_calculations.py)

The one thing simulated rather than real is persistence: `extracted_fields` is a plain dict here,
matching exactly what the JSONB column stores at rest (see extraction_guardrails.py's module
docstring for why) - this sidesteps needing SQLAlchemy/a live Postgres for what is otherwise a
fully real exercise of the pipeline's logic. DB-level persistence of this same flow is exercised
in tests/test_rls_integration.py's world (needs Docker) and in
app.services.contract_service.promote_extraction_fields (syntax-checked, not run - same
constraint as every DB-touching module all session).
"""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from app.ai.extraction_guardrails import promote_fields_from_extraction
from app.analytics.contract_calculations import (
    ContractStatus,
    calculate_next_renewal_date,
    calculate_notice_deadline,
    classify_contract_status,
    determine_due_alerts,
)
from app.core.exceptions import PermissionDeniedError, ValidationFailedError


def _raw_ai_extraction() -> dict[str, dict]:
    """Shape of a genuine AI-model response after JSON-parsing, matching
    app.ai.schemas.ContractExtractionOutput.fields once serialized to the extracted_fields JSONB
    column (see app.ai.contract_extraction_service.stage_extraction)."""
    return {
        "title": {"value": "Master Supply Agreement - Cape Valley Foods", "confidence": 0.97},
        "start_date": {"value": "2026-04-01", "confidence": 0.92},
        "expiry_date": {"value": "2027-03-31", "confidence": 0.95},
        "notice_period_days": {"value": "60", "confidence": 0.83},
        "auto_renew": {"value": "true", "confidence": 0.71},
        "renewal_term_months": {"value": "12", "confidence": 0.68},
        # escalation_rate_pct deliberately absent - the model didn't find a clear number in the
        # document; a well-behaved extraction says nothing rather than guessing (spec Section 26/
        # 109's anti-fabrication rule, exercised here at the extraction layer too).
    }


class TestUnverifiedExtractionIsBlocked(unittest.TestCase):
    """Step 1-2 of the requested pipeline: ingest -> stage as unverified -> assert blocked."""

    def test_pending_extraction_cannot_be_promoted(self):
        extracted_fields = _raw_ai_extraction()
        with self.assertRaises(PermissionDeniedError):
            promote_fields_from_extraction(
                extracted_fields, "pending",
                ["title", "start_date", "expiry_date", "notice_period_days"],
            )

    def test_rejected_extraction_cannot_be_promoted_either(self):
        # A human explicitly saying "no, this is wrong" must block promotion at least as firmly
        # as "nobody has looked yet" - ADR-004's guardrail treats both as not-verified.
        extracted_fields = _raw_ai_extraction()
        with self.assertRaises(PermissionDeniedError):
            promote_fields_from_extraction(extracted_fields, "rejected", ["title"])

    def test_unverified_block_happens_before_any_field_is_read(self):
        # Prove the gate actually runs first, not just that the end result happens to be empty -
        # a poisoned/malformed extracted_fields payload must not be touched at all while
        # unverified, not silently read-then-discarded.
        poisoned_fields = {"title": {"value": object(), "confidence": "not-a-number"}}
        with self.assertRaises(PermissionDeniedError):
            promote_fields_from_extraction(poisoned_fields, "pending", ["title"])


class TestUnknownFieldsRejected(unittest.TestCase):
    def test_promoting_a_non_contract_field_is_rejected_even_when_verified(self):
        extracted_fields = {"not_a_real_column": {"value": "x", "confidence": 0.9}}
        with self.assertRaises(ValidationFailedError):
            promote_fields_from_extraction(extracted_fields, "human_verified", ["not_a_real_column"])


class TestFullPipelineAfterHumanVerification(unittest.TestCase):
    """Step 3 of the requested pipeline: simulated human verification -> promotion -> the real
    calculation engine -> confirm alerts/deadlines/renewal dates."""

    def setUp(self):
        self.extracted_fields = _raw_ai_extraction()
        # The human verification step itself - in the real system this is
        # app.services.contract_service.promote_extraction_fields setting
        # extraction.verification_status = "human_verified" after a reviewer confirms the terms
        # against the signed document (spec Section 31). Simulated here as the status string the
        # gate actually checks.
        self.verification_status = "human_verified"

    def test_promotion_returns_only_the_requested_verified_fields(self):
        promoted = promote_fields_from_extraction(
            self.extracted_fields, self.verification_status,
            ["title", "start_date", "expiry_date", "notice_period_days", "auto_renew", "renewal_term_months"],
        )
        self.assertEqual(promoted["title"], "Master Supply Agreement - Cape Valley Foods")
        self.assertEqual(promoted["expiry_date"], "2027-03-31")
        # escalation_rate_pct was never in extracted_fields (the model didn't find it) - it must
        # not appear here even though it wasn't explicitly excluded from the request, and it must
        # not have been silently defaulted to anything either.
        self.assertNotIn("escalation_rate_pct", promoted)

    def test_promoted_fields_feed_the_real_calculation_engine_correctly(self):
        promoted = promote_fields_from_extraction(
            self.extracted_fields, self.verification_status,
            ["expiry_date", "notice_period_days", "auto_renew", "renewal_term_months"],
        )
        # The type coercion a real ORM column assignment would perform (str from JSONB -> date/
        # int/bool) - done explicitly here since this test deliberately doesn't touch SQLAlchemy.
        expiry_date = date.fromisoformat(promoted["expiry_date"])
        notice_period_days = int(promoted["notice_period_days"])
        auto_renew = promoted["auto_renew"].lower() == "true"
        renewal_term_months = int(promoted["renewal_term_months"])

        # From here on, every call is the real, separately-proven engine
        # (test_contract_calculations.py) - this test's job is only to prove the *promoted*
        # values produce correct results, not to re-prove the engine itself.
        notice_deadline = calculate_notice_deadline(expiry_date, notice_period_days)
        self.assertEqual(notice_deadline, date(2027, 1, 30))  # 60 days before 2027-03-31

        next_renewal = calculate_next_renewal_date(
            expiry_date, auto_renew=auto_renew, renewal_term_months=renewal_term_months
        )
        self.assertEqual(next_renewal, date(2028, 3, 31))

        status_well_before_expiry = classify_contract_status(
            date(2026, 6, 1), expiry_date, notice_deadline, auto_renew=auto_renew
        )
        self.assertEqual(status_well_before_expiry, ContractStatus.ACTIVE)

        status_after_notice_deadline = classify_contract_status(
            date(2027, 2, 15), expiry_date, notice_deadline, auto_renew=auto_renew
        )
        self.assertEqual(status_after_notice_deadline, ContractStatus.AUTO_RENEWING)

        due_alerts = determine_due_alerts(
            expiry_date - __import__("datetime").timedelta(days=90),
            expiry_date, notice_deadline, already_fired=set(),
        )
        self.assertIn("expiry_90", due_alerts)
        self.assertNotIn("expiry_30", due_alerts)

    def test_promoting_fewer_fields_than_extracted_only_returns_what_was_asked_for(self):
        # Per-field promotion (spec Section 31), proven by asking for a strict subset.
        promoted = promote_fields_from_extraction(
            self.extracted_fields, self.verification_status, ["title"]
        )
        self.assertEqual(list(promoted.keys()), ["title"])


if __name__ == "__main__":
    unittest.main()
