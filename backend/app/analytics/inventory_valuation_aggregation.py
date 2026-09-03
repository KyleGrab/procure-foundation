"""
Pure logic extracted from what would otherwise be DB-orchestration code in
app.services.inventory_valuation_service - zero DB/framework imports, §2.1. These are the two
genuinely pure pieces of the inventory valuation ingestion request: summing a batch's asset
valuation, and shaping the audit-log context dict. The actual DB writes (bulk insert into
inventory_snapshots, the period-lock query, the audit_logs insert) stay in the service module,
which is not pure and is tested in tests/, not here.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal


def calculate_batch_asset_valuation(records: list[dict]) -> Decimal:
    """
    Sum of quantity_on_hand * unit_cost across every record - always recomputed from these two
    fields, never summed from a per-record total_valuation, even if one is present. total_valuation
    is a cross-check field only (inventory_valuation_validation.py) - trusting it as the source of
    truth for the batch aggregate would let a source-data inconsistency silently propagate into a
    reported figure instead of being flagged and recomputed correctly. A record missing unit_cost
    contributes nothing rather than being treated as a $0 line.
    """
    total = Decimal("0")
    for record in records:
        quantity = record.get("quantity_on_hand")
        unit_cost = record.get("unit_cost")
        if quantity is not None and unit_cost is not None:
            total += quantity * unit_cost
    return total


def build_reconciliation_audit_context(
    *, record_count: int, total_asset_valuation: Decimal, snapshot_date: date, file_hash: str | None,
) -> dict:
    """
    Shape of the context dict passed to audit_service.record()'s existing `context: dict` JSONB
    column - not a new audit_logs-shaped table. Decimal/date are stringified since JSONB has no
    native representation for either. file_hash is omitted entirely when None, not stored as a
    JSON null, so a caller checking `"file_hash" in context` gets a clean answer either way.
    """
    context: dict = {
        "record_count": record_count,
        "total_asset_valuation": str(total_asset_valuation),
        "snapshot_date": snapshot_date.isoformat(),
    }
    if file_hash is not None:
        context["file_hash"] = file_hash
    return context
