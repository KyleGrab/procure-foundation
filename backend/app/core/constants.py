"""
Central enums / constants shared across the app. Keeping these in one place (rather than
scattered string literals) is what makes it possible to add a role or permission without
grepping the whole codebase.
"""
from enum import Enum


class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    EXECUTIVE = "executive"
    FINANCE = "finance"
    PROCUREMENT_MANAGER = "procurement_manager"
    BUYER = "buyer"
    OPERATIONS = "operations"
    ANALYST = "analyst"
    CONSULTANT = "consultant"
    VIEWER = "viewer"


class MembershipStatus(str, Enum):
    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REMOVED = "removed"


class Currency(str, Enum):
    """Compliance finding 3 (docs/compliance-review-2026-08.md): currency was an unconstrained
    `str` across 13 fields in 7 schema files - any 3-character string passed. A deliberately
    small, named allow-list (not a full 180-code ISO 4217 list) - this is a South African-focused
    platform, ZAR is the practical default everywhere; the rest are the common majors worth
    supporting now. Extending this list is a one-line addition, not a migration - it's an enum
    used at the Pydantic validation layer, not a DB column type."""
    ZAR = "ZAR"
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    AUD = "AUD"
    CHF = "CHF"


class Permission(str, Enum):
    UPLOAD_DATA = "upload_data"
    DELETE_DATASETS = "delete_datasets"
    VIEW_FINANCIALS = "view_financials"
    EDIT_SUPPLIERS = "edit_suppliers"
    APPROVE_OPPORTUNITIES = "approve_opportunities"
    CONFIGURE_INTEGRATIONS = "configure_integrations"
    VIEW_CONTRACTS = "view_contracts"
    MANAGE_USERS = "manage_users"
    GENERATE_REPORTS = "generate_reports"
    ACCESS_AI = "access_ai"
    EXPORT_DATA = "export_data"
    APPROVE_PRICE_INCREASES = "approve_price_increases"
    APPROVE_SAVINGS = "approve_savings"
    MANAGE_ORGANISATION = "manage_organisation"


# Role -> permission set. Deliberately explicit (no wildcard "admin gets everything" shortcut)
# so that adding a permission forces a conscious decision about which roles get it.
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: frozenset(p for p in Permission),
    Role.ADMIN: frozenset(
        p for p in Permission if p != Permission.MANAGE_ORGANISATION
    ),
    Role.EXECUTIVE: frozenset(
        {
            Permission.VIEW_FINANCIALS,
            Permission.VIEW_CONTRACTS,
            Permission.GENERATE_REPORTS,
            Permission.ACCESS_AI,
            Permission.APPROVE_OPPORTUNITIES,
            Permission.APPROVE_SAVINGS,
            Permission.EXPORT_DATA,
        }
    ),
    Role.FINANCE: frozenset(
        {
            Permission.VIEW_FINANCIALS,
            Permission.VIEW_CONTRACTS,
            Permission.GENERATE_REPORTS,
            Permission.ACCESS_AI,
            Permission.APPROVE_SAVINGS,
            Permission.EXPORT_DATA,
        }
    ),
    Role.PROCUREMENT_MANAGER: frozenset(
        {
            Permission.UPLOAD_DATA,
            Permission.VIEW_FINANCIALS,
            Permission.EDIT_SUPPLIERS,
            Permission.VIEW_CONTRACTS,
            Permission.GENERATE_REPORTS,
            Permission.ACCESS_AI,
            Permission.EXPORT_DATA,
            Permission.APPROVE_PRICE_INCREASES,
        }
    ),
    Role.BUYER: frozenset(
        {Permission.UPLOAD_DATA, Permission.ACCESS_AI, Permission.VIEW_FINANCIALS}
    ),
    Role.OPERATIONS: frozenset({Permission.VIEW_FINANCIALS, Permission.ACCESS_AI}),
    Role.ANALYST: frozenset(
        {Permission.VIEW_FINANCIALS, Permission.ACCESS_AI, Permission.GENERATE_REPORTS}
    ),
    Role.CONSULTANT: frozenset(
        {
            Permission.VIEW_FINANCIALS,
            Permission.GENERATE_REPORTS,
            Permission.ACCESS_AI,
            Permission.EXPORT_DATA,
        }
    ),
    Role.VIEWER: frozenset({Permission.VIEW_FINANCIALS}),
}
