"""Unit tests for the RBAC table itself - no DB needed, pure logic (spec Section 8)."""
from app.core.constants import ROLE_PERMISSIONS, Permission, Role


def test_owner_has_every_permission():
    assert ROLE_PERMISSIONS[Role.OWNER] == frozenset(Permission)


def test_viewer_cannot_manage_users():
    assert Permission.MANAGE_USERS not in ROLE_PERMISSIONS[Role.VIEWER]


def test_buyer_cannot_approve_price_increases():
    # Buyers work with product/quote data day to day but approval authority for a price increase
    # sits with procurement management - this is a business rule, not an oversight.
    assert Permission.APPROVE_PRICE_INCREASES not in ROLE_PERMISSIONS[Role.BUYER]


def test_every_role_has_at_least_one_permission():
    assert all(len(perms) > 0 for perms in ROLE_PERMISSIONS.values())
