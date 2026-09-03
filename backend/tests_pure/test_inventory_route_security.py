"""
Pure-logic tests behind "route security" for the inventory valuation upload endpoint.

TWO SEPARATE CONCERNS, DELIBERATELY NOT TREATED THE SAME WAY:

1. TestSerializeValidationIssues - genuinely pure, zero dependencies beyond this codebase's own
   stdlib-only app.ingestion.validation module. Runs cleanly here, every time.

2. TestDecodeAccessTokenErrorBehavior - pure BY DESIGN (zero DB/network - app.core.security's
   decode_access_token only ever reads a signed string and process env config), but importing it
   requires app.core.config, which requires the `pydantic-settings` package. That package is
   correctly declared in pyproject.toml but was never actually pip-installed in this sandbox
   (confirmed: `pip install pydantic_settings` fails here with no network, same as every other
   external-package constraint this sprint - this is not a DB dependency, it's a missing package).

   Discovered the hard way: an earlier version of this file imported app.core.config
   unconditionally, and the resulting ImportError silently killed EVERY test in this file
   (including the genuinely-runnable serializer tests) and turned the entire tests_pure/
   discovery run's overall result to FAILED. Wrapped below so that class is skipped cleanly,
   with an explicit reason, in an environment missing the package - and would run for real,
   unskipped, the moment `pip install -e ".[dev]"` actually succeeds (a real CI environment,
   for instance). Never silently hidden - `python3 -m unittest -v` prints exactly why each of
   those tests was skipped.

What NEITHER class claims to test: whether POST /inventory/upload-valuation itself returns
401/422/409/201. That needs a running FastAPI app and, past the missing-JWT case, a live
database - see tests/test_inventory_route_integration.py. An HTTP route's actual response codes
are an integration-test concern regardless of what a test file is named.
"""
from __future__ import annotations

import time
import unittest

from app.ingestion.validation import IssueSeverity, ValidationIssue, serialize_validation_issues

try:
    import jwt

    from app.core.config import get_settings
    from app.core.exceptions import AuthenticationError
    from app.core.security import create_access_token, decode_access_token
    _SECURITY_MODULE_AVAILABLE = True
    _SECURITY_IMPORT_ERROR = ""
except ImportError as exc:
    _SECURITY_MODULE_AVAILABLE = False
    _SECURITY_IMPORT_ERROR = str(exc)


class TestSerializeValidationIssues(unittest.TestCase):
    def test_shape_matches_what_a_diagnostic_field_error_array_needs(self):
        issues = [ValidationIssue(3, "unit_cost", IssueSeverity.ERROR, "Malformed unit cost: 'abc'")]
        serialized = serialize_validation_issues(issues)
        self.assertEqual(serialized, [{
            "row_number": 3, "field": "unit_cost", "severity": "error",
            "message": "Malformed unit cost: 'abc'",
        }])

    def test_severity_enum_is_serialized_as_its_plain_string_value(self):
        # A raw IssueSeverity.ERROR in a JSON response body would serialize incorrectly (or fail
        # outright) depending on the encoder - always the plain ("error"/"warning") string value.
        issues = [ValidationIssue(1, "x", IssueSeverity.WARNING, "msg")]
        self.assertEqual(serialize_validation_issues(issues)[0]["severity"], "warning")

    def test_empty_issue_list_returns_empty_list(self):
        self.assertEqual(serialize_validation_issues([]), [])

    def test_preserves_order_and_count_across_many_issues(self):
        issues = [ValidationIssue(i, f"field_{i}", IssueSeverity.ERROR, f"msg {i}") for i in range(1, 6)]
        serialized = serialize_validation_issues(issues)
        self.assertEqual([s["row_number"] for s in serialized], [1, 2, 3, 4, 5])


@unittest.skipUnless(
    _SECURITY_MODULE_AVAILABLE,
    f"app.core.security unimportable in this environment (missing package: {_SECURITY_IMPORT_ERROR}) - "
    f"not a DB dependency, purely a package that was never pip-installed here",
)
class TestDecodeAccessTokenErrorBehavior(unittest.TestCase):
    def test_valid_token_round_trips_correctly(self):
        token = create_access_token(user_id=42, active_org_id=7, role="owner")
        claims = decode_access_token(token)
        self.assertEqual(claims.user_id, 42)
        self.assertEqual(claims.active_org_id, 7)

    def test_garbage_string_raises_authentication_error_not_a_raw_jwt_exception(self):
        # The route layer only ever needs to catch ProcureIQError subclasses (main.py's generic
        # handler) - if this leaked a raw PyJWTError instead, that handler wouldn't catch it and
        # the client would see a raw 500 with a stack trace, not a clean 401.
        with self.assertRaises(AuthenticationError):
            decode_access_token("not-a-real-token")

    def test_empty_string_raises_authentication_error(self):
        with self.assertRaises(AuthenticationError):
            decode_access_token("")

    def test_expired_token_raises_authentication_error(self):
        settings = get_settings()
        expired_payload = {
            "sub": "42", "active_org_id": "7", "role": "owner", "type": "access",
            "iat": int(time.time()) - 7200, "exp": int(time.time()) - 3600,
        }
        expired_token = jwt.encode(expired_payload, settings.secret_key, algorithm=settings.jwt_algorithm)
        with self.assertRaises(AuthenticationError):
            decode_access_token(expired_token)

    def test_token_signed_with_a_different_secret_is_rejected(self):
        settings = get_settings()
        payload = {
            "sub": "42", "active_org_id": "7", "role": "owner", "type": "access",
            "iat": int(time.time()), "exp": int(time.time()) + 3600,
        }
        forged_token = jwt.encode(payload, "wrong-secret-key", algorithm=settings.jwt_algorithm)
        with self.assertRaises(AuthenticationError):
            decode_access_token(forged_token)

    def test_refresh_token_type_is_rejected_by_the_access_token_decoder(self):
        settings = get_settings()
        payload = {
            "sub": "42", "active_org_id": "7", "role": "owner", "type": "refresh",
            "iat": int(time.time()), "exp": int(time.time()) + 3600,
        }
        refresh_token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
        with self.assertRaises(AuthenticationError):
            decode_access_token(refresh_token)


if __name__ == "__main__":
    unittest.main()
