"""
DB orchestration for bulk inventory-valuation-report ingestion into inventory_snapshots
(ADR-018, append-only). Same period-locking shape as app.services.working_capital_service - an
application-level check against the target table's own corrects_id, reusing ConflictError, not a
separate lock table (none exists in this schema). Aggregate valuation and the audit-context shape
are computed by the real pure functions in app.analytics.inventory_valuation_aggregation - no
duplicated arithmetic here. The audit trail is a row in the existing audit_logs table via
audit_service.record(), not a separate table.

location_id is an explicit required parameter, not inferred - inventory_valuation_mapping.py's
canonical fields don't include a per-row location (the source Gourmet Inventory Valuation Report
was never successfully read to confirm whether it even represents one warehouse or several), and
InventorySnapshot.location_id is NOT NULL. Guessing at this would risk silently misattributing
every row to the wrong location; requiring the caller to state it explicitly (matching how a real
upload flow would ask "which warehouse is this for" before parsing) is the honest alternative.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.inventory_valuation_aggregation import (
    build_reconciliation_audit_context,
    calculate_batch_asset_valuation,
)
from app.core.exceptions import ConflictError
from app.db.models import InventorySnapshot
from app.services import audit_service


async def ingest_inventory_valuation(
    db: AsyncSession, *, organisation_id: int, user_id: int, location_id: int, snapshot_date: date,
    validated_records: list[dict], source_file_storage_key: str | None = None,
    file_hash: str | None = None, is_correction: bool = False,
) -> dict:
    """
    validated_records: the `parsed` dicts from
    app.ingestion.inventory_valuation_validation.validate_inventory_valuation_rows for rows where
    is_valid was True - this function does not re-validate; it trusts records that already passed
    that layer. Each needs at minimum supplier_sku, quantity_on_hand, unit_cost.

    Returns a dict (record_count, total_asset_valuation, snapshot_ids) rather than the raw ORM
    objects, since a caller ingesting a large batch shouldn't need to hold every inserted row's
    full object in memory just to know the summary.
    """
    existing_result = await db.execute(
        select(InventorySnapshot.id)
        .where(InventorySnapshot.organisation_id == organisation_id)
        .where(InventorySnapshot.location_id == location_id)
        .where(InventorySnapshot.snapshot_date == snapshot_date)
        .where(InventorySnapshot.corrects_id.is_(None))
    )
    existing_ids = [row[0] for row in existing_result.all()]
    if existing_ids and not is_correction:
        raise ConflictError(
            f"Active inventory snapshots already exist for location {location_id} on "
            f"{snapshot_date} - pass is_correction=True to supersede them, not silently duplicate"
        )
    # A correction supersedes every existing active row for this (org, location, date) grain -
    # each new row's corrects_id points at the specific row it replaces. Existing rows beyond the
    # batch size are left un-corrected (still active) only if the new batch is smaller - matching
    # ADR-018's grain (description, supplier_sku, location_id, snapshot_date) means a correction
    # batch is expected to supply a full replacement set, not a partial patch.
    corrects_iter = iter(existing_ids)

    inserted_ids: list[int] = []
    for record in validated_records:
        snapshot = InventorySnapshot(
            organisation_id=organisation_id, location_id=location_id, snapshot_date=snapshot_date,
            supplier_sku=record.get("supplier_sku"), description=record.get("description") or record["supplier_sku"],
            quantity_on_hand=record["quantity_on_hand"], unit_cost=record.get("unit_cost"),
            corrects_id=next(corrects_iter, None) if is_correction else None,
            source_file_storage_key=source_file_storage_key, uploaded_by_user_id=user_id,
        )
        db.add(snapshot)
        await db.flush()
        inserted_ids.append(snapshot.id)

    total_asset_valuation = calculate_batch_asset_valuation(validated_records)
    audit_context = build_reconciliation_audit_context(
        record_count=len(validated_records), total_asset_valuation=total_asset_valuation,
        snapshot_date=snapshot_date, file_hash=file_hash,
    )
    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id,
        action="inventory_valuation_corrected" if is_correction else "inventory_valuation_ingested",
        entity_type="inventory_snapshot", entity_id=None, context=audit_context,
    )
    await db.commit()

    return {
        "record_count": len(validated_records), "total_asset_valuation": total_asset_valuation,
        "snapshot_ids": inserted_ids,
    }
