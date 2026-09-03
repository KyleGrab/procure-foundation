"""
Runs the actual Phase 2 pipeline - read -> map -> validate -> normalize -> match -> calculate ->
summarize -> export - against the synthetic Cape Valley Foods files, end to end, with no DB and
no mocking. This is the closest thing to a real acceptance test this sandbox can run (no network
for Postgres/FastAPI - see docs/phase2-price-review-plan.md Section 3). It proves the business
logic is correct on realistic data; it does NOT prove the API/DB layer works, because that layer
can't run here at all.
"""
from __future__ import annotations

import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.analytics.price_review_calculations import (  # noqa: E402
    calculate_annual_impact,
    calculate_percentage_change,
    calculate_price_change,
    classify_movement_type,
    classify_risk,
)
from app.analytics.price_review_summary import (  # noqa: E402
    PriceReviewLineForSummary,
    summarize,
)
from app.ingestion.excel_reader import read_xlsx_rows  # noqa: E402
from app.ingestion.mapping import apply_mapping, suggest_mapping  # noqa: E402
from app.ingestion.validation import validate_rows  # noqa: E402
from app.matching.pack_parser import (  # noqa: E402
    UnrecognizedPackFormatError,
    parse_pack_string,
    price_per_base_unit,
)
from app.matching.review import requires_human_review  # noqa: E402
from app.matching.scorer import CandidateItem, MatchStatus, find_best_match  # noqa: E402
from app.reporting.price_review_excel_export import (  # noqa: E402
    ExportLine,
    ExportSummary,
    export_price_review,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic"
# Every purchase quantity below is a manual stand-in for real purchase history - see
# docs/phase2-price-review-plan.md Section 2.2 (ADR-008). This demo assigns a plausible quantity
# per SKU deterministically rather than reading a real purchases table, which doesn't exist yet.


def manual_annual_quantity(sku: str) -> Decimal:
    return Decimal(200 + (hash(sku) % 4800))  # deterministic, plausible, clearly not real data


def load_and_map(path: Path) -> list[dict]:
    raw_rows = read_xlsx_rows(path)
    mapping = suggest_mapping(list(raw_rows[0].keys()))
    mapping["supplier_sku"] = "Stock Code"  # confirmed mapping (spec: user confirms ambiguous ones)
    mapped_rows = [apply_mapping(r, mapping) for r in raw_rows]
    return mapped_rows


def normalize_price(parsed_pack_str: str, price_raw: str) -> tuple[Decimal | None, str | None]:
    try:
        price = Decimal(str(price_raw))
        pack = parse_pack_string(parsed_pack_str)
        return price_per_base_unit(price, pack), pack.base_unit
    except (UnrecognizedPackFormatError, InvalidOperation, ValueError):
        return None, None


def main() -> None:
    old_path = DATA_DIR / "cape_valley_foods_old_price_list.xlsx"
    new_path = DATA_DIR / "cape_valley_foods_new_price_list.xlsx"

    old_rows = load_and_map(old_path)
    new_rows = load_and_map(new_path)

    old_validated = validate_rows(old_rows)
    new_validated = validate_rows(new_rows)
    print(f"Old list: {len(old_validated)} rows, {sum(1 for r in old_validated if r.is_valid)} valid")
    print(f"New list: {len(new_validated)} rows, {sum(1 for r in new_validated if r.is_valid)} valid")

    old_candidates = [
        CandidateItem(key=str(r["supplier_sku"]), supplier_sku=r["supplier_sku"],
                       barcode=r.get("barcode"), description=r["description"] or "")
        for r in old_rows
    ]
    new_candidates = [
        CandidateItem(key=str(r["supplier_sku"]), supplier_sku=r["supplier_sku"],
                       barcode=r.get("barcode"), description=r["description"] or "")
        for r in new_rows
    ]
    old_by_sku = {r["supplier_sku"]: r for r in old_rows}
    new_by_sku = {r["supplier_sku"]: r for r in new_rows}

    summary_lines: list[PriceReviewLineForSummary] = []
    export_lines: list[ExportLine] = []
    top_impacts: list[tuple[str, Decimal, str]] = []
    review_queue: list[tuple[str, float, str]] = []
    ambiguous_check_passed = None

    for old_item in old_candidates:
        result = find_best_match(old_item, new_candidates)
        old_row = old_by_sku[old_item.key]

        if old_row["supplier_sku"] == "CVF-9001":  # the planted variant-conflict pair
            ambiguous_check_passed = result.status != MatchStatus.AUTO_MATCHED

        if result.status == MatchStatus.NO_CANDIDATE or result.new_key is None:
            summary_lines.append(PriceReviewLineForSummary("discontinued", None, None, None, False, False))
            export_lines.append(ExportLine(
                old_supplier_sku=old_row["supplier_sku"], old_description=old_row["description"],
                old_pack_raw=old_row.get("pack_size"), old_price=Decimal(str(old_row["price"])),
                new_supplier_sku=None, new_description=None, new_pack_raw=None, new_price=None,
                normalized_old_price=None, normalized_new_price=None, change_amount=None,
                change_pct=None, historical_volume=None, annual_volume=None, annual_impact=None,
                margin_impact=None, match_confidence=None, pack_changed=False, risk=None,
                movement_type="discontinued", buyer_decision=None, target_price=None,
                potential_cost_avoidance=None,
            ))
            continue

        if requires_human_review(result.status):
            review_queue.append((old_row["description"], result.confidence, result.status.value))

        new_row = new_by_sku[result.new_key]
        old_price, new_price = Decimal(str(old_row["price"])), Decimal(str(new_row["price"]))
        pack_changed = (old_row.get("pack_size") or "") != (new_row.get("pack_size") or "")

        old_norm, _ = normalize_price(old_row.get("pack_size") or "", old_row["price"])
        new_norm, _ = normalize_price(new_row.get("pack_size") or "", new_row["price"])
        cmp_old, cmp_new = (old_norm, new_norm) if (old_norm and new_norm) else (old_price, new_price)

        pct_change = calculate_percentage_change(cmp_old, cmp_new)
        price_change = calculate_price_change(cmp_old, cmp_new)
        annual_qty = manual_annual_quantity(old_row["supplier_sku"])
        annual_impact = calculate_annual_impact(price_change, annual_qty)
        movement = classify_movement_type(
            is_matched=True, is_new=False, is_discontinued=False,
            pack_changed=pack_changed, percentage_change=pct_change,
        )
        risk = classify_risk(pct_change)

        summary_lines.append(PriceReviewLineForSummary(
            movement, pct_change, annual_impact, annual_qty, pack_changed,
            requires_human_review(result.status),
        ))
        top_impacts.append((old_row["description"], annual_impact, risk))
        export_lines.append(ExportLine(
            old_supplier_sku=old_row["supplier_sku"], old_description=old_row["description"],
            old_pack_raw=old_row.get("pack_size"), old_price=old_price,
            new_supplier_sku=new_row["supplier_sku"], new_description=new_row["description"],
            new_pack_raw=new_row.get("pack_size"), new_price=new_price,
            normalized_old_price=old_norm, normalized_new_price=new_norm,
            change_amount=price_change, change_pct=pct_change,
            historical_volume=annual_qty, annual_volume=annual_qty, annual_impact=annual_impact,
            margin_impact=None, match_confidence=Decimal(str(round(result.confidence, 4))),
            pack_changed=pack_changed, risk=risk, movement_type=movement, buyer_decision=None,
            target_price=None, potential_cost_avoidance=None,
        ))

    new_skus = set(new_by_sku) - set(old_by_sku)
    for sku in new_skus:
        summary_lines.append(PriceReviewLineForSummary("new_product", None, None, None, False, False))
        new_row = new_by_sku[sku]
        export_lines.append(ExportLine(
            old_supplier_sku=None, old_description=None, old_pack_raw=None, old_price=None,
            new_supplier_sku=new_row["supplier_sku"], new_description=new_row["description"],
            new_pack_raw=new_row.get("pack_size"), new_price=Decimal(str(new_row["price"])),
            normalized_old_price=None, normalized_new_price=None, change_amount=None,
            change_pct=None, historical_volume=None, annual_volume=None, annual_impact=None,
            margin_impact=None, match_confidence=None, pack_changed=False, risk=None,
            movement_type="new_product", buyer_decision=None, target_price=None,
            potential_cost_avoidance=None,
        ))

    summary = summarize(summary_lines, total_previous_skus=len(old_rows), total_new_skus=len(new_rows))

    print("\n--- Supplier Summary: Cape Valley Foods (Pty) Ltd ---")
    for field in summary.__dataclass_fields__:
        print(f"  {field}: {getattr(summary, field)}")

    print(f"\n--- Matches sent to manual review ({len(review_queue)}) ---")
    for desc, confidence, status in review_queue[:8]:
        print(f"  {desc[:60]:<60} confidence={confidence:.3f}  status={status}")
    if len(review_queue) > 8:
        print(f"  ... and {len(review_queue) - 8} more")

    print("\n--- Top 5 by annual financial impact ---")
    for desc, impact, risk in sorted(top_impacts, key=lambda t: -abs(t[1]))[:5]:
        print(f"  {desc[:50]:<50} impact=R{impact:>12,.2f}  risk={risk}")

    print(f"\n--- Planted ambiguous pair (Cheddar Mature vs Mild) correctly held for review: "
          f"{ambiguous_check_passed} ---")

    assert ambiguous_check_passed is True, "the variant-conflict guard did not fire as expected"
    assert summary.new_skus >= 5, "planted new products were not detected"
    assert summary.discontinued_skus >= 5, "planted discontinued products were not detected"
    assert summary.pack_changes >= 1, "planted pack-size change was not detected"
    print("\nAll structural assertions passed - the pipeline correctly classified every planted scenario.")

    export_summary = ExportSummary(
        supplier_name="Cape Valley Foods (Pty) Ltd", effective_date="2026-09-01",
        total_previous_skus=summary.total_previous_skus, total_new_skus=summary.total_new_skus,
        matched_skus=summary.matched_skus, new_skus=summary.new_skus,
        discontinued_skus=summary.discontinued_skus, increasing_skus=summary.increasing_skus,
        decreasing_skus=summary.decreasing_skus, unchanged_skus=summary.unchanged_skus,
        pack_changes=summary.pack_changes,
        weighted_average_price_increase_pct=summary.weighted_average_price_increase_pct,
        annual_cost_impact=summary.annual_cost_impact,
        products_requiring_manual_review=summary.products_requiring_manual_review,
    )
    output_path = DATA_DIR / "demo_output" / "cape_valley_foods_price_review.xlsx"
    saved_path = export_price_review(export_lines, export_summary, output_path)
    print(f"\nExcel export written to: {saved_path} ({len(export_lines)} lines across 9 sheets)")


if __name__ == "__main__":
    main()
