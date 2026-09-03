"""D-01 pure tests - the exception shape, and the settings fields' own default/override
behavior. The actual guard behavior (register() raising it, login remaining unaffected) requires
a live database/HTTP client per this codebase's own test infrastructure - written separately in
tests/test_auth.py, not executed here. The docs_url/openapi_url 404 check now has a real,
executable HTTP test too (tests/test_auth.py, via app.main.create_app()'s fresh-construction
pattern) - the Settings-level tests below are a genuine, additional, narrower proof (the field
parses correctly at all), not a substitute for that integration test.

TestD01SettingsDefaults needs app.core.config, which needs the `pydantic-settings` package -
correctly declared in pyproject.toml but never actually installed in this sandbox (same
pre-existing, documented environment gap as tests_pure/test_inventory_route_security.py's
TestDecodeAccessTokenErrorBehavior - not a DB dependency, purely a missing package). Skipped
explicitly here, matching that file's exact pattern, rather than left to surface as a bare
ImportError-driven test failure."""
import unittest

from app.core.exceptions import RegistrationDisabledError

try:
    from app.core.config import Settings  # noqa: F401
    _CONFIG_MODULE_AVAILABLE = True
    _CONFIG_IMPORT_ERROR = None
except ImportError as e:
    _CONFIG_MODULE_AVAILABLE = False
    _CONFIG_IMPORT_ERROR = e


class TestRegistrationDisabledError(unittest.TestCase):
    def test_code_and_status(self):
        err = RegistrationDisabledError("test")
        self.assertEqual(err.code, "registration_disabled")
        self.assertEqual(err.status_code, 403)

    def test_is_a_procureiq_error(self):
        from app.core.exceptions import ProcureIQError
        self.assertIsInstance(RegistrationDisabledError("test"), ProcureIQError)


@unittest.skipUnless(
    _CONFIG_MODULE_AVAILABLE,
    f"app.core.config unimportable in this environment (missing package: {_CONFIG_IMPORT_ERROR}) - "
    f"not a DB dependency, purely a package that was never pip-installed here",
)
class TestD01SettingsDefaults(unittest.TestCase):
    """Constructs Settings directly (bypassing get_settings()'s cache and the .env file) -
    genuinely pure, no DB/HTTP dependency, only this one package availability gap."""

    def _settings(self, **overrides):
        from app.core.config import Settings
        base = {
            "database_url": "postgresql+asyncpg://x:x@localhost/x",
            "database_url_sync": "postgresql+psycopg://x:x@localhost/x",
            "database_url_app": "postgresql+asyncpg://x:x@localhost/x",
            "secret_key": "test",
        }
        base.update(overrides)
        return Settings(**base)

    def test_allow_self_registration_defaults_true(self):
        self.assertTrue(self._settings().allow_self_registration)

    def test_enable_api_docs_defaults_true(self):
        self.assertTrue(self._settings().enable_api_docs)

    def test_both_can_be_explicitly_overridden_false(self):
        s = self._settings(allow_self_registration=False, enable_api_docs=False)
        self.assertFalse(s.allow_self_registration)
        self.assertFalse(s.enable_api_docs)


if __name__ == "__main__":
    unittest.main()
