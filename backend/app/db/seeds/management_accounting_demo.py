"""
Demo data for the management accounting canvas lens, grounded in Gourmet Cape Distributors
(Pty) Ltd's real, uploaded financial statements wherever real figures were available - not
invented numbers described as if they were. `seed_management_accounting_demo` is importable and
parameterless (creates its own demo Organisation) so both the standalone script (`__main__`
below) and `tests/api/test_canvas_management_demo.py` call the exact same seeding logic - one
source of truth for the demo numbers, not two places that could quietly drift apart.

REAL figures (pulled directly from the uploaded workbooks, cell references given inline so anyone
can re-verify independently - none of this was estimated):
- Income Statement sheet, Gourmet_Reporting_Pack_2026_July__26_NEW_NEW.xlsx: July 2026 Net Sales
  and Net Cost of Sales (row 9/17, column 25), and trailing-twelve-month sums of both ending
  July 2026 and June 2026 (used as annualized_revenue/annualized_cogs - a single month's figure
  divided into AR/AP would badly overstate DSO/DPO, so this uses a genuine TTM sum, not one
  month annualized by multiplication).
- Balance Sheet sheet, same workbook: Trade receivables, Trade Creditors, Inventory, and Cash and
  Cash equivalents for July 2026 (column 37) and June 2026 (column 36) - rows 21/24/39/96.
  Cash is genuinely negative (an overdraft position) in both periods - preserved as the real
  figure, not smoothed into a nicer-looking positive number.
- tem_daily_truck_revenue_sheet0.xlsx, Sheet2: one real delivery route (Vehicle CAA 127155,
  "West Coast" route, 3 July 2026, 24 drops) - the "Trip total" row gives real weight, Cost of
  Sale, and Sales Ex VAT, used as the volumetric (Level 3) CostToServeLedger row.

GENUINE GAPS, filled with clearly-labeled illustrative values (never presented as sourced):
- No route in the Daily Truck Revenue sheet had a recorded fuel/toll expense line (checked
  across 6+ routes - the "Daily expenses recorded for" section was empty in every case checked).
  direct_logistics_cost for the real West Coast route is therefore an illustrative estimate
  (8% of that route's real Cost of Sale), not a sourced figure - flagged at the point it's used.
- CostAllocationRule unit rates (picking/receiving/logistics R-per-unit) aren't present in any
  P&L/Balance Sheet - these are internal costing assumptions no financial statement would show.
  Illustrative, hand-verifiable.
- Level 1 (direct) and Level 2 (activity_rate) CostToServeLedger rows are illustrative - the real
  data found only supports a Level 3 (volumetric, weight-based) row for one real route.
- Debtors/creditors aging BUCKETS aren't in the Balance Sheet (only period-end totals are) -
  illustrative bucket amounts, deliberately NOT constructed to sum to the real AR/AP totals
  above, since implying that sum would misrepresent illustrative numbers as if they were a real
  aging breakdown of the actual receivables book.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.analytics.management_accounting import (  # noqa: E402
    calculate_customer_net_margin,
    calculate_variance_vs_prior,
    calculate_working_capital_metrics,
    classify_aging_buckets,
    resolve_trade_spend_for_period,
)
from app.core.security import hash_password  # noqa: E402
from app.db.models import (  # noqa: E402
    AgingLedgerSnapshot,
    CostAllocationRule,
    CostToServeLedger,
    Organisation,
    OrganisationMembership,
    User,
    WorkingCapitalSnapshot,
)

DEMO_ORG_NAME = "ProcureIQ Demo Co - Management Accounting (Gourmet-informed)"
DEMO_EMAIL = "demo@management-accounting.procureiq.example"
DEMO_PASSWORD = "demo-password-change-me"


async def seed_management_accounting_demo(db: AsyncSession) -> dict:
    organisation = Organisation(name=DEMO_ORG_NAME, default_currency="ZAR", country="ZA")
    db.add(organisation)
    await db.flush()

    user = User(
        first_name="Demo", last_name="Analyst", email=DEMO_EMAIL,
        password_hash=hash_password(DEMO_PASSWORD), verified=True,
    )
    db.add(user)
    await db.flush()

    db.add(OrganisationMembership(user_id=user.id, organisation_id=organisation.id, role="owner", status="active"))

    # Illustrative config - no P&L/Balance Sheet shows internal per-unit costing assumptions.
    # is_fallback_rate=False explicitly on all three (Chaos Audit Domain 1) - these are genuine,
    # deliberately-set illustrative rates, not averaged stand-ins, so False is the honest answer
    # here - the point of removing the default was never "always pass True," it was "never let
    # the answer go unstated."
    db.add_all([
        CostAllocationRule(
            organisation_id=organisation.id, cost_category="warehouse_picking",
            allocation_method="activity_rate", default_unit_rate=Decimal("2.50"), set_by_user_id=user.id,
            is_fallback_rate=False,
        ),
        CostAllocationRule(
            organisation_id=organisation.id, cost_category="receiving",
            allocation_method="activity_rate", default_unit_rate=Decimal("15.00"), set_by_user_id=user.id,
            is_fallback_rate=False,
        ),
        CostAllocationRule(
            organisation_id=organisation.id, cost_category="outbound_logistics",
            allocation_method="volumetric", default_unit_rate=Decimal("8.00"), set_by_user_id=user.id,
            is_fallback_rate=False,
        ),
    ])

    # Row 1: REAL - tem_daily_truck_revenue_sheet0.xlsx, Sheet2, row 42 ("Trip total for :
    # CAA 127155") - Vehicle CAA 127155, "West Coast" route, 3 July 2026, 24 real drops.
    # direct_logistics_cost is the one illustrative figure on this otherwise-real row (see
    # module docstring - no fuel/toll expense was recorded for this route in the source sheet).
    real_route_revenue = Decimal("45189.62")
    real_route_cogs = Decimal("36686.08")
    real_route_weight_kg = Decimal("686.435")
    real_route_illustrative_logistics_cost = round(real_route_cogs * Decimal("0.08"), 2)  # illustrative 8% estimate

    # Rows 2-3: illustrative (Level 1 direct, Level 2 activity_rate) - clean, hand-verifiable
    # numbers, not sourced from any uploaded file (see module docstring).
    ledger_rows_input = [
        {
            "invoice_id": "GOURMET-WESTCOAST-15110", "customer_id": "ROUTE-WEST-COAST",
            "allocation_level": "volumetric", "source": "real",
            "revenue": real_route_revenue, "cogs": real_route_cogs,
            "direct_logistics_cost": real_route_illustrative_logistics_cost,
            "warehouse_abc_cost": round(real_route_weight_kg * Decimal("2.50"), 2),  # per warehouse_picking rate above
        },
        {
            "invoice_id": "DEMO-INV-002", "customer_id": "DEMO-CUST-B",
            "allocation_level": "activity_rate", "source": "illustrative",
            "revenue": Decimal("20000"), "cogs": Decimal("13000"),
            "direct_logistics_cost": Decimal("1200"), "warehouse_abc_cost": Decimal("600"),
        },
        {
            "invoice_id": "DEMO-INV-003", "customer_id": "DEMO-CUST-C",
            "allocation_level": "direct", "source": "illustrative",
            "revenue": Decimal("5000"), "cogs": Decimal("3200"),
            "direct_logistics_cost": Decimal("400"), "warehouse_abc_cost": Decimal("150"),
        },
    ]
    ledger_totals = {
        "revenue": Decimal("0"), "cogs": Decimal("0"), "logistics": Decimal("0"),
        "warehouse": Decimal("0"), "net_margin": Decimal("0"),
    }
    for row in ledger_rows_input:
        # Chaos Audit Domain 1: goes through resolve_trade_spend_for_period() explicitly, not a
        # bare Decimal("0") - these demo rows genuinely have no sell-side agreement, and routing
        # even that through the real gate function (rather than a hardcoded literal that happens
        # to equal what the gate would return) means this call site can never silently drift out
        # of sync with the gate's own logic if that logic changes.
        resolved_trade_spend = resolve_trade_spend_for_period(trade_spend_record=None, agreement_exists=False)
        margin_result = calculate_customer_net_margin(
            revenue=row["revenue"], cogs=row["cogs"],
            direct_logistics_cost=row["direct_logistics_cost"], warehouse_abc_cost=row["warehouse_abc_cost"],
            trade_spend=resolved_trade_spend, revenue_basis="gross",
            # "gross" - Chaos Audit re-audit fix: these demo rows use raw revenue directly, never
            # calculate_gross_to_net_waterfall's output, so "gross" is the honest, correct basis -
            # not "net_of_waterfall", which would be a false claim about data that was never
            # actually run through that function.
        )
        db.add(CostToServeLedger(
            organisation_id=organisation.id, invoice_id=row["invoice_id"], customer_id=row["customer_id"],
            net_revenue=row["revenue"], cogs=row["cogs"],
            direct_logistics_cost=row["direct_logistics_cost"], allocated_warehouse_cost=row["warehouse_abc_cost"],
            allocated_overhead_cost=Decimal("0"),
            net_margin=margin_result["net_margin"], net_margin_pct=margin_result["net_margin_pct"],
            allocation_level=row["allocation_level"], uploaded_by_user_id=user.id,
        ))
        ledger_totals["revenue"] += row["revenue"]
        ledger_totals["cogs"] += row["cogs"]
        ledger_totals["logistics"] += row["direct_logistics_cost"]
        ledger_totals["warehouse"] += row["warehouse_abc_cost"]
        ledger_totals["net_margin"] += margin_result["net_margin"]

    # WorkingCapitalSnapshot: REAL figures for both periods.
    # Balance Sheet sheet, column 36 (June 2026) / column 37 (July 2026); rows 21 (Inventory),
    # 24 (Trade receivables / AR), 39 (Cash and Cash equivalents), 96 (Trade Creditors / AP).
    # annualized_revenue/annualized_cogs are REAL trailing-twelve-month sums of Income Statement
    # rows 9 (Net Sales) / 17 (Net Cost of Sales), not one month multiplied by 12.
    prior_metrics = calculate_working_capital_metrics(
        ar=Decimal("31485762.45"), ap=Decimal("27022967.28"), inventory=Decimal("22378736.13"),
        annual_revenue=Decimal("351249755.03"), annual_cogs=Decimal("286778833.06"),
        cash=Decimal("-13522349.72"),  # real overdraft position, June 2026
    )
    db.add(WorkingCapitalSnapshot(
        organisation_id=organisation.id, as_of_date=date(2026, 6, 30),
        accounts_receivable=Decimal("31485762.45"), accounts_payable=Decimal("27022967.28"),
        inventory_value=Decimal("22378736.13"), cash_balance=Decimal("-13522349.72"),
        annualized_revenue=Decimal("351249755.03"), annualized_cogs=Decimal("286778833.06"),
        dso=prior_metrics["dso"], dio=prior_metrics["dio"], dpo=prior_metrics["dpo"], ccc=prior_metrics["ccc"],
        working_capital_ratio=prior_metrics["working_capital_ratio"], uploaded_by_user_id=user.id,
    ))

    current_metrics = calculate_working_capital_metrics(
        ar=Decimal("31596977.24"), ap=Decimal("23532821.46"), inventory=Decimal("22249299.99"),
        annual_revenue=Decimal("355848477.03"), annual_cogs=Decimal("290075966.07"),
        cash=Decimal("-19518395.79"),  # real overdraft position, July 2026
    )
    db.add(WorkingCapitalSnapshot(
        organisation_id=organisation.id, as_of_date=date(2026, 7, 31),
        accounts_receivable=Decimal("31596977.24"), accounts_payable=Decimal("23532821.46"),
        inventory_value=Decimal("22249299.99"), cash_balance=Decimal("-19518395.79"),
        annualized_revenue=Decimal("355848477.03"), annualized_cogs=Decimal("290075966.07"),
        dso=current_metrics["dso"], dio=current_metrics["dio"], dpo=current_metrics["dpo"], ccc=current_metrics["ccc"],
        working_capital_ratio=current_metrics["working_capital_ratio"], uploaded_by_user_id=user.id,
    ))

    # AgingLedgerSnapshot: illustrative buckets (the Balance Sheet has no aging breakdown, only
    # period-end totals) - deliberately NOT summed to equal the real AR/AP totals above, so these
    # never look like a real breakdown of the actual receivables/payables book.
    debtors_invoices = [
        {"amount": Decimal("200000"), "days_overdue": 10}, {"amount": Decimal("150000"), "days_overdue": 35},
        {"amount": Decimal("100000"), "days_overdue": 65}, {"amount": Decimal("50000"), "days_overdue": 95},
        {"amount": Decimal("25000"), "days_overdue": 130},
    ]
    debtors_buckets = classify_aging_buckets(debtors_invoices)
    db.add(AgingLedgerSnapshot(
        organisation_id=organisation.id, as_of_date=date(2026, 7, 31), ledger_type="debtors",
        current_balance=debtors_buckets["current"], days_30=debtors_buckets["days_30"],
        days_60=debtors_buckets["days_60"], days_90=debtors_buckets["days_90"],
        days_120_plus=debtors_buckets["days_120_plus"], uploaded_by_user_id=user.id,
    ))

    creditors_invoices = [
        {"amount": Decimal("180000"), "days_overdue": 5}, {"amount": Decimal("80000"), "days_overdue": 40},
        {"amount": Decimal("40000"), "days_overdue": 70},
    ]
    creditors_buckets = classify_aging_buckets(creditors_invoices)
    db.add(AgingLedgerSnapshot(
        organisation_id=organisation.id, as_of_date=date(2026, 7, 31), ledger_type="creditors",
        current_balance=creditors_buckets["current"], days_30=creditors_buckets["days_30"],
        days_60=creditors_buckets["days_60"], days_90=creditors_buckets["days_90"],
        days_120_plus=creditors_buckets["days_120_plus"], uploaded_by_user_id=user.id,
    ))

    await db.commit()

    return {
        "organisation_public_id": str(organisation.public_id),
        "login_email": DEMO_EMAIL, "login_password": DEMO_PASSWORD,
        "expected": {
            "gross_revenue": ledger_totals["revenue"], "cogs": ledger_totals["cogs"],
            "warehouse_abc_cost": ledger_totals["warehouse"], "logistics_cost": ledger_totals["logistics"],
            "net_margin": ledger_totals["net_margin"],
            "current_dso": current_metrics["dso"], "current_dio": current_metrics["dio"],
            "current_dpo": current_metrics["dpo"], "current_ccc": current_metrics["ccc"],
            "dso_variance": calculate_variance_vs_prior(current_metrics["dso"], prior_metrics["dso"]),
            "dio_variance": calculate_variance_vs_prior(current_metrics["dio"], prior_metrics["dio"]),
            "dpo_variance": calculate_variance_vs_prior(current_metrics["dpo"], prior_metrics["dpo"]),
            "debtors_buckets": debtors_buckets, "creditors_buckets": creditors_buckets,
        },
    }


async def _run_standalone() -> None:
    from app.core.config import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        result = await seed_management_accounting_demo(db)
        print(f"Seeded organisation {DEMO_ORG_NAME!r}, login {result['login_email']} / {result['login_password']}")
        print(f"Expected figures: {result['expected']}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run_standalone())
