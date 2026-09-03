"""
Route profitability ingestion endpoint. Follows app/api/v1/inventory.py's established pattern
exactly - JWT-derived active_org_id (never client-supplied), the global 503 DatabaseUnavailableError
wrapping (automatic via Depends(get_db), no route-specific code needed), 422 via
ValidationFailedError with a structured details array, never an unstructured 400.

Runs app.matching.route_log_validation.validate_route_log_plausibility BEFORE the profitability
calculation, as explicitly required - a route log that's physically impossible (zero km with
real drops, drop weight exceeding vehicle capacity) is rejected before its cost figures are ever
computed or persisted, not after.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.logistics_engine import (
    calculate_distance_variable_cost,
    calculate_drop_latency_demurrage_cost,
    calculate_trip_fixed_cost,
    calculate_warehouse_picking_labor_cost,
)
from app.core.constants import Permission
from app.core.exceptions import EvidenceRequiredError, NotFoundError, ValidationFailedError
from app.core.permissions import require_permission
from app.core.security import AccessTokenClaims
from app.db.models import Location
from app.db.session import get_db
from app.matching.route_log_validation import validate_route_log_plausibility
from app.services.route_profitability_service import ingest_route_profitability

router = APIRouter(prefix="/logistics", tags=["logistics"])


class RouteProfitabilityRequest(BaseModel):
    trip_date: date
    location_public_id: str | None = None
    customer_id: str | None = None
    vehicle_registration: str | None = None
    route_reference: str | None = None

    # Raw telematics - checked for physical plausibility before anything else runs.
    distance_km: Decimal
    stop_count: int
    total_drop_weight_kg: Decimal
    vehicle_max_payload_kg: Decimal

    # Revenue/COGS
    revenue: Decimal
    cogs: Decimal
    trade_spend: Decimal
    revenue_basis: str

    # Granular cost pools
    driver_base_salary: Decimal
    co_driver_base_salary: Decimal
    fixed_vehicle_asset_cost: Decimal
    stem_distance_km: Decimal
    drop_distance_km: Decimal
    base_rate_per_km: Decimal
    stop_start_multiplier: Decimal
    sku_line_count: int
    total_cube_m3: Decimal
    rate_per_line: Decimal
    rate_per_cube_m3: Decimal
    time_at_bay_minutes: Decimal
    free_time_minutes: Decimal
    demurrage_rate_per_minute: Decimal


@router.post("/route-profitability", status_code=201)
async def create_route_profitability(
    payload: RouteProfitabilityRequest,
    claims: AccessTokenClaims = Depends(require_permission(Permission.UPLOAD_DATA)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # F-03 (fail-closed, foundation hardening): auth (require_permission) and tenant context
    # (get_db's own SET_config('app.current_org_id', ...)) are already fully resolved by this
    # point via FastAPI's Depends chain, before this function body ever runs - so this is the
    # earliest point a business-logic guard can sit. No evidenced revenue/COGS/trade-spend source
    # exists anywhere in this codebase yet (confirmed by direct search before this change was
    # made), so caller-supplied revenue/cogs/trade_spend can never be processed as if they were
    # real financial facts. This raises before plausibility checks, cost-pool calculations,
    # calculate_true_route_profitability, ingest_route_profitability, or any database write -
    # unconditionally, not as a partial gate, because there is currently nothing to gate against.
    raise EvidenceRequiredError(
        "Route profitability requires evidenced, reconciled source facts, which do not yet "
        "exist in this system. Caller-supplied revenue, cost, and trade-spend figures cannot "
        "be persisted or returned as actual route profitability.",
        details=[{"field": "revenue_basis", "message": "no evidenced source-fact model exists yet"}],
    )

    # Plausibility check FIRST, before any cost figure is computed or touched - a physically
    # impossible route log must never reach the calculation layer at all.
    violations = validate_route_log_plausibility(
        distance_km=payload.distance_km, stop_count=payload.stop_count,
        total_drop_weight_kg=payload.total_drop_weight_kg, vehicle_max_payload_kg=payload.vehicle_max_payload_kg,
    )
    if violations:
        raise ValidationFailedError(
            "Route log failed physical plausibility validation",
            details=[{"field": "telematics", "message": v} for v in violations],
        )

    # Resolve the PUBLIC location_id (what the client sends) to the internal integer id the
    # service layer needs - never trust a client-supplied primary key directly (§1), same
    # pattern as app/api/v1/inventory.py, scoped to claims.active_org_id so a location
    # belonging to a different organisation can never be targeted.
    internal_location_id = None
    if payload.location_public_id is not None:
        location_result = await db.execute(
            select(Location.id)
            .where(Location.public_id == uuid.UUID(payload.location_public_id))
            .where(Location.organisation_id == claims.active_org_id)
        )
        internal_location_id = location_result.scalar_one_or_none()
        if internal_location_id is None:
            raise NotFoundError(f"Location {payload.location_public_id} not found")

    # Cost pools built via the real, tested pure functions - never reimplemented here.
    try:
        trip_fixed_costs = calculate_trip_fixed_cost(
            driver_base_salary=payload.driver_base_salary, co_driver_base_salary=payload.co_driver_base_salary,
            fixed_vehicle_asset_cost=payload.fixed_vehicle_asset_cost,
        )
        distance_variable = calculate_distance_variable_cost(
            stem_distance_km=payload.stem_distance_km, drop_distance_km=payload.drop_distance_km,
            base_rate_per_km=payload.base_rate_per_km, stop_start_multiplier=payload.stop_start_multiplier,
        )
        picking_cost = calculate_warehouse_picking_labor_cost(
            sku_line_count=payload.sku_line_count, total_cube_m3=payload.total_cube_m3,
            rate_per_line=payload.rate_per_line, rate_per_cube_m3=payload.rate_per_cube_m3,
        )
        demurrage_cost = calculate_drop_latency_demurrage_cost(
            time_at_bay_minutes=payload.time_at_bay_minutes, free_time_minutes=payload.free_time_minutes,
            demurrage_rate_per_minute=payload.demurrage_rate_per_minute,
        )
    except (ValueError, TypeError) as exc:
        # Explicit mapping, per this phase's own requirement - caught here rather than left to
        # propagate, since main.py's generic handler only recognizes ProcureIQError subclasses,
        # not raw ValueError/TypeError.
        raise ValidationFailedError(
            "Cost pool calculation failed validation", details=[{"field": "cost_pools", "message": str(exc)}],
        ) from exc

    activity_time_costs = picking_cost + demurrage_cost

    try:
        result = await ingest_route_profitability(
            db, organisation_id=claims.active_org_id, user_id=claims.user_id, trip_date=payload.trip_date,
            revenue=payload.revenue, cogs=payload.cogs, trade_spend=payload.trade_spend,
            revenue_basis=payload.revenue_basis, trip_fixed_costs=trip_fixed_costs,
            distance_variable_costs=distance_variable["total"], activity_time_costs=activity_time_costs,
            location_id=internal_location_id, customer_id=payload.customer_id,
            vehicle_registration=payload.vehicle_registration,
            route_reference=payload.route_reference,
        )
    except (ValueError, TypeError) as exc:
        raise ValidationFailedError(
            "Route profitability calculation failed validation", details=[{"field": "revenue_basis", "message": str(exc)}],
        ) from exc

    return {
        "snapshot_id": result["snapshot_id"], "snapshot_public_id": result["snapshot_public_id"],
        "net_net_profit": str(result["net_net_profit"]), "is_net_revenue_negative": result["is_net_revenue_negative"],
        "gross_margin": str(result["gross_margin"]),
        "cost_breakdown": {
            "trip_fixed_costs": str(result["trip_fixed_costs"]),
            "distance_variable_costs": str(result["distance_variable_costs"]),
            "activity_time_costs": str(result["activity_time_costs"]),
        },
    }
