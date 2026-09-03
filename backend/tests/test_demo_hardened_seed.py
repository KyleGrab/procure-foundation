"""D-01: proves app/db/seeds/demo_hardened_seed.py's idempotency claim directly - calling it
twice must reuse the same organisation and user, never create a second of either. Written, not
executed here - same pre-existing sandbox gap as every DB-dependent test this engagement
(pydantic-settings missing, no live Postgres)."""
import os

from sqlalchemy import func, select

from app.db.models import Organisation, User
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
