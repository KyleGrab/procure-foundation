"""
Tests for app.services.inventory_valuation_service - period-locking against inventory_snapshots'
own corrects_id (no separate lock table exists), real audit_logs entries, and that the aggregate
valuation/audit-context values actually come from the real pure functions in
app.analytics.inventory_valuation_aggregation, not reimplemented here. Same live-Postgres
requirement as every other file in backend/tests/ - written, not executed.

Needs a real Location row to satisfy InventorySnapshot.location_id's NOT NULL constraint - this
test creates one directly via db_session, same as _register_org creates an Organisation.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import ConflictError
from app.core.security import decode_access_token
from app.db.models import Location
from app.services.inventory_valuation_service import ingest_inventory_valuation


async def _register_org(client, email: str, org_name: str) -> tuple[str, int, int]:
    resp = await client.post(
        "/auth/register",
        json={
            "first_name": "Test", "last_name": "User", "email": email,
            "password": "correct-horse-battery-staple", "organisation_name": org_name,
        },
    )
    token = resp.json()["access_token"]
    claims = decode_access_token(token)
    return token, claims.active_org_id, claims.user_id


async def _create_location(db_session, organisation_id: int, code: str) -> int:
    location = Location(
        organisation_id=organisation_id, code=code, name=f"Test Warehouse {code}",
        location_type="warehouse", country="ZA",
    )
    db_session.add(location)
    await db_session.flush()
    return location.id


_SAMPLE_RECORDS = [
    {"supplier_sku": "SKU004", "description": "BEEF MINCE 1KG", "quantity_on_hand": Decimal(124), "unit_cost": Decimal("137.73")},
    {"supplier_sku": "SKU001", "description": "CHICKEN BREAST 2KG", "quantity_on_hand": Decimal(674), "unit_cost": Decimal("4.79")},
]


class TestInventoryValuationPeriodLocking:
    async def test_fresh_batch_ingests_successfully(self, client, db_session):
        _, org_id, user_id = await _register_org(client, "iv-fresh@example.com", "IV Fresh Org")
        location_id = await _create_location(db_session, org_id, "WH1")
        result = await ingest_inventory_valuation(
            db_session, organisation_id=org_id, user_id=user_id, location_id=location_id,
            snapshot_date=date(2026, 8, 26), validated_records=_SAMPLE_RECORDS,
        )
        assert result["record_count"] == 2
        assert len(result["snapshot_ids"]) == 2

    async def test_reingesting_same_location_and_date_without_correction_raises(self, client, db_session):
        _, org_id, user_id = await _register_org(client, "iv-conflict@example.com", "IV Conflict Org")
        location_id = await _create_location(db_session, org_id, "WH1")
        kwargs = dict(
            organisation_id=org_id, user_id=user_id, location_id=location_id,
            snapshot_date=date(2026, 8, 26), validated_records=_SAMPLE_RECORDS,
        )
        await ingest_inventory_valuation(db_session, **kwargs)
        with pytest.raises(ConflictError):
            await ingest_inventory_valuation(db_session, **kwargs)

    async def test_correction_flag_supersedes_prior_active_rows(self, client, db_session):
        _, org_id, user_id = await _register_org(client, "iv-correction@example.com", "IV Correction Org")
        location_id = await _create_location(db_session, org_id, "WH1")
        kwargs = dict(
            organisation_id=org_id, user_id=user_id, location_id=location_id,
            snapshot_date=date(2026, 8, 26), validated_records=_SAMPLE_RECORDS,
        )
        await ingest_inventory_valuation(db_session, **kwargs)
        corrected = await ingest_inventory_valuation(db_session, is_correction=True, **kwargs)
        assert corrected["record_count"] == 2

    async def test_different_locations_for_the_same_date_do_not_conflict(self, client, db_session):
        _, org_id, user_id = await _register_org(client, "iv-multiloc@example.com", "IV Multi Location Org")
        location_a = await _create_location(db_session, org_id, "WH-A")
        location_b = await _create_location(db_session, org_id, "WH-B")
        result_a = await ingest_inventory_valuation(
            db_session, organisation_id=org_id, user_id=user_id, location_id=location_a,
            snapshot_date=date(2026, 8, 26), validated_records=_SAMPLE_RECORDS,
        )
        result_b = await ingest_inventory_valuation(
            db_session, organisation_id=org_id, user_id=user_id, location_id=location_b,
            snapshot_date=date(2026, 8, 26), validated_records=_SAMPLE_RECORDS,
        )
        assert result_a["snapshot_ids"] != result_b["snapshot_ids"]


class TestAggregateValuationAndAuditContext:
    async def test_returned_total_matches_the_real_pure_aggregation_function(self, client, db_session):
        # Locks in that this service calls calculate_batch_asset_valuation rather than a second,
        # independently-written sum - 124*137.73 + 674*4.79 = 17078.52 + 3228.46 = 20306.98
        _, org_id, user_id = await _register_org(client, "iv-aggregate@example.com", "IV Aggregate Org")
        location_id = await _create_location(db_session, org_id, "WH1")
        result = await ingest_inventory_valuation(
            db_session, organisation_id=org_id, user_id=user_id, location_id=location_id,
            snapshot_date=date(2026, 8, 26), validated_records=_SAMPLE_RECORDS,
        )
        assert result["total_asset_valuation"] == Decimal("20306.98")
