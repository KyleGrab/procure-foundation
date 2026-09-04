"""
D-01: creates exactly one controlled demo login user, in the same organisation as
management_accounting_demo.py's demo data - distinct from BOTH that module's own hardcoded
DEMO_EMAIL (now disclosed, never to be reused for anything reachable) and dev_demo_credentials.py's
dev-demo@procureiq.local (same reasoning, gated by NODE_ENV on the frontend but never actually
protected at the database/API level).

Idempotent by explicit checking, not by relying on unique-constraint errors to signal "already
done": queries for the demo organisation and demo user by their own stable identifiers before
creating either. A second run safely reuses both and reports so clearly - it never creates a
second demo organisation (Organisation has no DB-level unique constraint on name, confirmed
directly - the check here is the only thing preventing a duplicate) and never attempts to
re-insert a user whose email already exists (which would otherwise fail on User.email's real,
DB-enforced unique constraint - checked explicitly first, for a clear message instead of a raw
IntegrityError).

DEMO_USER_PASSWORD is required from the environment - this script refuses to run without it,
never falls back to any default, hardcoded, or previously-disclosed value.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.security import hash_password
from app.db.models import Organisation, OrganisationMembership, User
from app.db.seeds.management_accounting_demo import (
    DEMO_ORG_NAME,
    seed_management_accounting_demo,
)

DEMO_LOGIN_EMAIL = "demo-login@procureiq-demo.example"


async def seed_demo_hardened(db: AsyncSession) -> dict:
    demo_user_password = os.environ.get("DEMO_USER_PASSWORD")
    if not demo_user_password:
        raise RuntimeError(
            "DEMO_USER_PASSWORD is not set. This script refuses to run without it - "
            "there is no default, hardcoded, or previously-disclosed fallback."
        )

    org_result = await db.execute(select(Organisation).where(Organisation.name == DEMO_ORG_NAME))
    organisation = org_result.scalar_one_or_none()

    if organisation is None:
        seed_result = await seed_management_accounting_demo(db)
        org_result = await db.execute(select(Organisation).where(Organisation.name == DEMO_ORG_NAME))
        organisation = org_result.scalar_one()
        demo_data_status = "created"
    else:
        demo_data_status = "reused - already existed"

    user_result = await db.execute(select(User).where(User.email == DEMO_LOGIN_EMAIL))
    user = user_result.scalar_one_or_none()

    if user is not None:
        return {
            "organisation_public_id": str(organisation.public_id),
            "demo_data_status": demo_data_status,
            "user_status": "reused - already existed, password unchanged by this run",
            "login_email": DEMO_LOGIN_EMAIL,
        }

    user = User(
        first_name="Demo", last_name="User", email=DEMO_LOGIN_EMAIL,
        password_hash=hash_password(demo_user_password), verified=True,
    )
    db.add(user)
    await db.flush()

    membership_result = await db.execute(
        select(OrganisationMembership)
        .where(OrganisationMembership.user_id == user.id)
        .where(OrganisationMembership.organisation_id == organisation.id)
    )
    if membership_result.scalar_one_or_none() is None:
        db.add(OrganisationMembership(
            user_id=user.id, organisation_id=organisation.id, role="owner", status="active",
        ))

    await db.commit()

    return {
        "organisation_public_id": str(organisation.public_id),
        "demo_data_status": demo_data_status,
        "user_status": "created",
        "login_email": DEMO_LOGIN_EMAIL,
    }


async def _run_standalone() -> None:
    from app.core.config import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        result = await seed_demo_hardened(db)
        print(f"Organisation: {result['organisation_public_id']} ({result['demo_data_status']})")
        print(f"Demo login user: {result['login_email']} ({result['user_status']})")
        print("Password is whatever DEMO_USER_PASSWORD was set to - never printed here.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run_standalone())
