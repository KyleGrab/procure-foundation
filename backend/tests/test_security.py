"""Unit tests for password hashing and JWT round-trip - no DB needed."""
import time

import pytest

from app.core.exceptions import AuthenticationError
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password


def test_password_hash_roundtrip():
    hashed = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", hashed)
    assert not verify_password("wrong-password", hashed)


def test_access_token_roundtrip():
    token = create_access_token(user_id=1, active_org_id=42, role="owner")
    claims = decode_access_token(token)
    assert claims.user_id == 1
    assert claims.active_org_id == 42
    assert claims.role == "owner"


def test_access_token_does_not_carry_other_org_memberships():
    # Structural assertion for ADR-007: the only organisation identifier anywhere in the token
    # is active_org_id. There is no field a client could read to enumerate other orgs the user
    # belongs to, because it was never put there.
    token = create_access_token(user_id=1, active_org_id=42, role="owner")
    claims = decode_access_token(token)
    assert not hasattr(claims, "organisations")
    assert not hasattr(claims, "memberships")
