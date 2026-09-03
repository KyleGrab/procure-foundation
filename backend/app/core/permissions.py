"""
RBAC permission dependency. Spec Section 8 is explicit that backend permission checks are
mandatory and frontend hiding is not sufficient -- this module is where that's enforced, as a
FastAPI dependency injected into every mutating route, never as a decision made in the route
body after the fact.
"""
from __future__ import annotations

from fastapi import Depends

from app.core.constants import ROLE_PERMISSIONS, Permission, Role
from app.core.exceptions import PermissionDeniedError
from app.core.security import AccessTokenClaims
from app.db.session import get_current_claims


def require_permission(permission: Permission):
    def _check(claims: AccessTokenClaims = Depends(get_current_claims)) -> AccessTokenClaims:
        role = Role(claims.role)
        if permission not in ROLE_PERMISSIONS.get(role, frozenset()):
            raise PermissionDeniedError(
                f"Role '{role.value}' does not have permission '{permission.value}'"
            )
        return claims

    return _check
