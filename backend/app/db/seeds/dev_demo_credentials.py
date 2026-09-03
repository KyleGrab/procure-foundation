"""
Dev-only demo credentials seed - explicitly temporary, per direct instruction: to be removed
before this goes anywhere near production. NOT a login bypass - this creates a real user with a
real, hashed password that goes through the exact same POST /auth/login flow, real JWT issuance,
real RLS scoping as every other user. The convenience is a pre-filled login form (frontend,
dev-environment-gated), not a skipped authentication step.

role="owner" - "full access for testing" as requested, matching the real, existing role/status
values this codebase's RBAC already recognizes (see management_accounting_demo.py's identical
pattern - no new role invented for this).

seed_demo_credentials is importable and parameterless (creates its own demo Organisation), same
one-source-of-truth shape as seed_management_accounting_demo - the standalone script and any
future test call the exact same seeding logic.
"""
from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.db.models import Organisation, OrganisationMembership, User

DEMO_ORG_NAME = "ProcureIQ Dev Demo Org"
DEMO_EMAIL = "dev-demo@procureiq.local"
DEMO_PASSWORD = "dev-demo-only-not-for-production"  # nosec - dev-only, real hash still applied


async def seed_demo_credentials(db) -> dict:
    """
    Real user, real bcrypt-hashed password (hash_password - the same function every real
    registration uses, never a shortcut), real organisation, real "owner" membership. Returns
    the plaintext email/password only so the frontend's dev-only pre-fill button and this
    script's own __main__ output can display them - never logged or stored anywhere in plaintext
    beyond this return value.
    """
    organisation = Organisation(name=DEMO_ORG_NAME, default_currency="ZAR", country="ZA")
    db.add(organisation)
    await db.flush()

    user = User(
        first_name="Dev", last_name="Demo", email=DEMO_EMAIL,
        password_hash=hash_password(DEMO_PASSWORD), verified=True,
    )
    db.add(user)
    await db.flush()

    db.add(OrganisationMembership(user_id=user.id, organisation_id=organisation.id, role="owner", status="active"))
    await db.commit()

    return {
        "email": DEMO_EMAIL, "password": DEMO_PASSWORD,
        "organisation_id": organisation.id, "user_id": user.id,
    }


async def _run_standalone() -> None:
    from app.core.config import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        result = await seed_demo_credentials(db)
        print(f"Dev demo user seeded: {result['email']} / {result['password']}")
        print("Remove this seed and the frontend's dev-only login button before production.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run_standalone())
