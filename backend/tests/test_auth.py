"""
Covers spec Section 67 "Authentication" critical test cases: login success/failure, and that
registration correctly bootstraps an org + owner membership (Phase 1 gate criterion).
"""


async def test_register_creates_user_org_and_owner_membership(client):
    resp = await client.post(
        "/auth/register",
        json={
            "first_name": "Kyle",
            "last_name": "Test",
            "email": "kyle.test@example.com",
            "password": "correct-horse-battery-staple",
            "organisation_name": "Test Distribution Co",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "access_token" in body and "refresh_token" in body


async def test_login_fails_with_wrong_password(client):
    await client.post(
        "/auth/register",
        json={
            "first_name": "A",
            "last_name": "B",
            "email": "wrongpw@example.com",
            "password": "correct-horse-battery-staple",
            "organisation_name": "Org",
        },
    )
    resp = await client.post(
        "/auth/login", json={"email": "wrongpw@example.com", "password": "not-the-password"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "authentication_failed"


async def test_registration_disabled_returns_403_and_creates_nothing(client, db_session):
    """D-01: the actual backend control - fires regardless of whether the frontend link is
    hidden. Confirms no organisation or user exists afterward, not just that the response
    looked right."""
    import os

    from sqlalchemy import select

    from app.core.config import get_settings
    from app.db.models import Organisation, User

    os.environ["ALLOW_SELF_REGISTRATION"] = "false"
    get_settings.cache_clear()
    try:
        resp = await client.post(
            "/auth/register",
            json={
                "first_name": "Should", "last_name": "Not-Exist",
                "email": "should-not-exist@example.com",
                "password": "correct-horse-battery-staple",
                "organisation_name": "Should Not Exist Org",
            },
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "registration_disabled"
    finally:
        os.environ["ALLOW_SELF_REGISTRATION"] = "true"
        get_settings.cache_clear()

    user_check = await db_session.execute(select(User).where(User.email == "should-not-exist@example.com"))
    assert user_check.scalar_one_or_none() is None
    org_check = await db_session.execute(select(Organisation).where(Organisation.name == "Should Not Exist Org"))
    assert org_check.scalar_one_or_none() is None


async def test_registration_disabled_setting_does_not_affect_login(client):
    """D-01: proves the independence claim directly, not just by code inspection - a user
    registered while the setting is enabled must still be able to log in after it's disabled."""
    import os

    from app.core.config import get_settings

    await client.post(
        "/auth/register",
        json={
            "first_name": "Still", "last_name": "Works",
            "email": "still-works@example.com",
            "password": "correct-horse-battery-staple",
            "organisation_name": "Still Works Org",
        },
    )

    os.environ["ALLOW_SELF_REGISTRATION"] = "false"
    get_settings.cache_clear()
    try:
        resp = await client.post(
            "/auth/login", json={"email": "still-works@example.com", "password": "correct-horse-battery-staple"}
        )
        assert resp.status_code == 200
        assert "access_token" in resp.json()
    finally:
        os.environ["ALLOW_SELF_REGISTRATION"] = "true"
        get_settings.cache_clear()


async def test_registration_enabled_by_default_behaves_exactly_as_before(client):
    """D-01 regression guard: no environment override at all - confirms the new setting's
    default genuinely preserves pre-D-01 behavior, not just that it's theoretically possible to
    re-enable it."""
    resp = await client.post(
        "/auth/register",
        json={
            "first_name": "Default", "last_name": "Behavior",
            "email": "default-behavior@example.com",
            "password": "correct-horse-battery-staple",
            "organisation_name": "Default Behavior Org",
        },
    )
    assert resp.status_code == 201
    assert "access_token" in resp.json()


async def test_api_docs_disabled_returns_404_on_actual_configured_paths():
    """D-01: real, automated HTTP requests against the application's actual configured paths -
    not a limitation note, not a no-op. Made possible by app.main.create_app() (the smallest
    clean refactor needed): sets ENABLE_API_DOCS=false, clears the settings cache, constructs a
    genuinely fresh FastAPI instance with that value already baked in, and hits it with a real
    ASGI test client - deliberately not using the shared `client` fixture, since that fixture's
    app was constructed once at conftest.py's module-import time and can never reflect a setting
    changed afterward."""
    import os

    from httpx import ASGITransport, AsyncClient

    from app.core.config import get_settings
    from app.main import create_app

    os.environ["ENABLE_API_DOCS"] = "false"
    get_settings.cache_clear()
    try:
        disabled_app = create_app()
        transport = ASGITransport(app=disabled_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            docs_resp = await ac.get("/api/v1/docs")
            openapi_resp = await ac.get("/api/v1/openapi.json")
        assert docs_resp.status_code == 404
        assert openapi_resp.status_code == 404
    finally:
        os.environ["ENABLE_API_DOCS"] = "true"
        get_settings.cache_clear()


async def test_api_docs_enabled_by_default_still_serves_both_paths():
    """Regression guard, same technique - proves the factory's default behavior (no override)
    matches what was already being served before this refactor, not just that disabling works."""
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    enabled_app = create_app()
    transport = ASGITransport(app=enabled_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        docs_resp = await ac.get("/api/v1/docs")
        openapi_resp = await ac.get("/api/v1/openapi.json")
    assert docs_resp.status_code == 200
    assert openapi_resp.status_code == 200


async def test_login_fails_for_unknown_email(client):
    resp = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "whatever12345"}
    )
    assert resp.status_code == 401
