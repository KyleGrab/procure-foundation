"""
Password hashing (Argon2id) and JWT issue/verify. See docs/security.md section 1 and 3.1 for
why the token deliberately carries only one active_org_id rather than the user's full
membership list (ADR-007).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError

_hasher = PasswordHasher()


def hash_password(plain_password: str) -> str:
    return _hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, plain_password)
    except VerifyMismatchError:
        return False


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: int
    active_org_id: int
    role: str
    issued_at: int
    expires_at: int


def create_access_token(*, user_id: int, active_org_id: int, role: str) -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "active_org_id": active_org_id,
        "role": role,
        "iat": now,
        "exp": now + settings.access_token_expire_minutes * 60,
        "type": "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> AccessTokenClaims:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid access token") from exc

    if payload.get("type") != "access":
        raise AuthenticationError("Wrong token type")

    return AccessTokenClaims(
        user_id=int(payload["sub"]),
        active_org_id=int(payload["active_org_id"]),
        role=str(payload["role"]),
        issued_at=int(payload["iat"]),
        expires_at=int(payload["exp"]),
    )


def create_refresh_token(*, user_id: int, family_id: str) -> str:
    """
    Refresh tokens are opaque to the client but carry a family_id so that reuse of a rotated-out
    token can invalidate the whole family (standard refresh-token-rotation defense).
    The hashed token + family_id + org membership is what's actually stored server-side;
    see services/auth_service.py for the persistence side of rotation.
    """
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "family_id": family_id,
        "iat": now,
        "exp": now + settings.refresh_token_expire_days * 86400,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
