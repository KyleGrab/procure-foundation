"""
DB orchestration for route profitability snapshots. No calculation logic of its own -
app.analytics.logistics_engine.calculate_true_route_profitability (real, tested,
tests_pure/test_route_profitability.py) does every number. This module's only real logic is
persistence and the correction (append-only) pattern - matching working_capital_service.py's
established shape, not inventing a new one for this domain.

No period-locking here, deliberately different from working_capital_service.py: multiple real
trips genuinely happen on the same trip_date for the same organisation (a whole fleet runs
routes daily) - "one snapshot per date" would be wrong for this domain, unlike a single daily
working-capital position. is_correction/corrects_id still exists for genuinely re-ingesting a
specific trip's corrected figures, scoped by the caller providing the prior row's id directly,
not by a date-based lookup.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.logistics_engine import calculate_true_route_profitability
from app.db.models import RouteProfitabilitySnapshot
from app.services import audit_service


async def ingest_route_profitability(
    db: AsyncSession, *, organisation_id: int, user_id: int, trip_date: date,
    revenue: Decimal, cogs: Decimal, trade_spend: Decimal, revenue_basis: str,
    trip_fixed_costs: Decimal, distance_variable_costs: Decimal, activity_time_costs: Decimal,
    location_id: int | None = None, customer_id: str | None = None,
    vehicle_registration: str | None = None, route_reference: str | None = None,
    corrects_id: int | None = None,
) -> dict:
    """
    Calls calculate_true_route_profitability (raises ValueError/TypeError on any invalid or
    missing input - never reaches this function's DB write on bad data) and persists the result.
    Returns the computed profitability dict plus the new row's id - the caller (the route
    handler) decides how to shape the HTTP response, this function only returns real data.
    """
    result = calculate_true_route_profitability(
        revenue=revenue, cogs=cogs, trade_spend=trade_spend, revenue_basis=revenue_basis,
        trip_fixed_costs=trip_fixed_costs, distance_variable_costs=distance_variable_costs,
        activity_time_costs=activity_time_costs,
    )

    snapshot = RouteProfitabilitySnapshot(
        organisation_id=organisation_id, trip_date=trip_date, location_id=location_id,
        customer_id=customer_id, vehicle_registration=vehicle_registration, route_reference=route_reference,
        revenue=revenue, cogs=cogs, trade_spend=trade_spend, revenue_basis=revenue_basis,
        trip_fixed_costs=trip_fixed_costs, distance_variable_costs=distance_variable_costs,
        activity_time_costs=activity_time_costs,
        net_net_profit=result["net_net_profit"], is_net_revenue_negative=result["is_net_revenue_negative"],
        corrects_id=corrects_id, uploaded_by_user_id=user_id,
    )
    db.add(snapshot)
    await db.flush()

    await audit_service.record(
        db, organisation_id=organisation_id, user_id=user_id,
        action="route_profitability_corrected" if corrects_id else "route_profitability_ingested",
        entity_type="route_profitability_snapshot", entity_id=snapshot.id,
        context={"trip_date": trip_date.isoformat(), "vehicle_registration": vehicle_registration},
    )
    await db.commit()

    return {"snapshot_id": snapshot.id, "snapshot_public_id": str(snapshot.public_id), **result}
