"""
The ADR-004 gate, factored out as pure functions so it's actually unit-tested (see
tests_pure/test_adr004_staging_pipeline.py) rather than only existing inline inside a
DB-dependent service function nobody can run in this sandbox. app/services/contract_service.py's
promote_extraction_fields() calls these - it does no gating logic of its own, only DB I/O around
what these functions decide.

No SQLAlchemy/Pydantic/FastAPI imports here on purpose - this module operates on the plain dict
shape a JSONB column actually stores (`{field_name: {"value": ..., "confidence": ...}}`), which
is also what makes it testable in an environment with no network to install those packages.
"""
from __future__ import annotations

from app.core.exceptions import PermissionDeniedError, ValidationFailedError

ALLOWED_PROMOTION_FIELDS = frozenset({
    "title", "contract_number", "start_date", "expiry_date", "notice_period_days",
    "auto_renew", "renewal_term_months", "payment_terms_days", "escalation_type",
    "escalation_rate_pct", "rebate_terms_summary", "sla_terms_summary",
    "minimum_spend_commitment",
})


def ensure_verified(verification_status: str) -> None:
    """The literal ADR-004 gate: nothing past this line runs unless a human explicitly verified
    the extraction. 'pending' and 'rejected' are both blocked - a rejected extraction is not a
    lesser form of verified, it's a human explicitly saying no, and must be at least as blocked
    as one nobody has looked at yet."""
    if verification_status != "human_verified":
        raise PermissionDeniedError(
            f"Cannot promote fields from an extraction with verification_status="
            f"{verification_status!r} - only 'human_verified' extractions may feed the "
            f"calculation engine (ADR-004)"
        )


def select_promotable_fields(
    extracted_fields: dict[str, dict], field_names: list[str]
) -> dict[str, str]:
    """Field-by-field selection (spec Section 31's per-field verification), never all-or-nothing.
    Raises on any requested field name outside the allowlist - a caller asking to promote a field
    that was never a real Contract column is almost certainly a bug, not a legitimate request."""
    unknown = set(field_names) - ALLOWED_PROMOTION_FIELDS
    if unknown:
        raise ValidationFailedError(f"Cannot promote unrecognised fields: {sorted(unknown)}")

    selected: dict[str, str] = {}
    for field_name in field_names:
        entry = extracted_fields.get(field_name)
        if entry is None:
            continue  # the model didn't extract this field - nothing to promote, not an error
        selected[field_name] = entry["value"]
    return selected


def promote_fields_from_extraction(
    extracted_fields: dict[str, dict], verification_status: str, field_names: list[str],
) -> dict[str, str]:
    """
    The full guarded pipeline as one call: ensure_verified() runs first and raises before
    select_promotable_fields() is ever reached for an unverified extraction. This ordering - not
    just each function individually - is the actual ADR-004 guarantee, which is why it's worth
    having one function that enforces the order rather than trusting every caller to remember it.
    """
    ensure_verified(verification_status)
    return select_promotable_fields(extracted_fields, field_names)
