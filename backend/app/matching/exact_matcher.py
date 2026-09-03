"""Stages 1-3 of the matching pipeline (spec Section 8): exact supplier SKU, barcode, and exact
normalized description. Each returns None if it can't produce a match - the orchestrator in
scorer.py falls through to the next stage rather than these functions guessing."""
from __future__ import annotations

from app.matching.normalize import normalize_description


def match_by_sku(old_sku: str | None, new_sku: str | None) -> bool:
    if not old_sku or not new_sku:
        return False
    return old_sku.strip().lower() == new_sku.strip().lower()


def match_by_barcode(old_barcode: str | None, new_barcode: str | None) -> bool:
    if not old_barcode or not new_barcode:
        return False
    return old_barcode.strip() == new_barcode.strip()


def match_by_exact_normalized_description(old_desc: str | None, new_desc: str | None) -> bool:
    if not old_desc or not new_desc:
        return False
    return normalize_description(old_desc) == normalize_description(new_desc)


def verify_exact_match_for_route_log(
    logged_vehicle_registration: str, source_system_vehicle_registration: str,
    logged_route_reference: str, source_system_route_reference: str,
) -> bool:
    """
    Gate B structural guardrail: a transport route log feeding a cost-to-serve pool must match
    its source system reference EXACTLY (vehicle registration, route reference) or be rejected
    outright - never accepted on a similarity score. This is deliberately NOT routed through
    scorer.py/find_best_match (this module's own fuzzy-matching orchestrator) - that machinery
    exists for supplier/SKU deduplication, a human-reviewed problem where a wrong match gets
    caught before it touches a number. A route log has no such review step between a match and a
    booked Rand figure, so "close enough" has no place here at all, not even at a high
    confidence threshold - strict equality only, case/whitespace-normalized for real-world data
    entry variance (not similarity scoring - normalizing casing is not the same risk as scoring
    a one-character difference as a probable match).
    """
    return (
        logged_vehicle_registration.strip().upper() == source_system_vehicle_registration.strip().upper()
        and logged_route_reference.strip().upper() == source_system_route_reference.strip().upper()
    )
