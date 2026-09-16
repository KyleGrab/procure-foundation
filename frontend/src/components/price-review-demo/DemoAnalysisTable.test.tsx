import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { DemoAnalysisTable } from "./DemoAnalysisTable";
import type { PriceReviewLine } from "@/types/price-review";

function line(overrides: Partial<PriceReviewLine>): PriceReviewLine {
  return {
    public_id: "line-1",
    old_supplier_sku: null,
    old_description: "Illustrative Widget",
    old_pack_raw: null,
    old_price: null,
    new_supplier_sku: null,
    new_description: null,
    new_pack_raw: null,
    new_price: null,
    match_status: "matched",
    match_confidence: null,
    movement_type: null,
    percentage_change: null,
    annual_impact: null,
    risk_classification: null,
    buyer_decision: null,
    target_price: null,
    potential_cost_avoidance: null,
    ...overrides,
  };
}

describe("DemoAnalysisTable", () => {
  it("renders every unknown (null) field as an em dash, never 0 or R0 or 0%", () => {
    render(
      <DemoAnalysisTable
        lines={[line({ public_id: "l1", old_price: null, new_price: null, percentage_change: null, match_confidence: null })]}
        filter="all"
        onFilterChange={() => {}}
        onSelectLine={() => {}}
      />
    );
    const row = screen.getByText("Illustrative Widget").closest("tr")!;
    const cells = Array.from(row.querySelectorAll("td")).map((cell) => cell.textContent);
    expect(cells).toContain("—");
    expect(cells.join(" ")).not.toMatch(/(^|\s)0%|R0(\.00)?(\s|$)/);
  });

  it("preserves the exact Decimal string of a financial value, including trailing zeros, via thousands-grouped rendering", () => {
    render(
      <DemoAnalysisTable
        lines={[line({ public_id: "l1", old_price: "96330.00", new_price: "96330.00" })]}
        filter="all"
        onFilterChange={() => {}}
        onSelectLine={() => {}}
      />
    );
    // Not "R96330" or "R96,330" (both would be Number()-derived and would drop the exact
    // trailing-zero precision the Decimal string carries) - the full string survives rendering.
    expect(screen.getAllByText("R96,330.00")).toHaveLength(2);
  });

  it("renders a genuinely known zero (e.g. an unchanged price's 0% movement) as a real zero, distinct from unknown", () => {
    render(
      <DemoAnalysisTable
        lines={[line({ public_id: "l1", percentage_change: "0", old_price: "125.00", new_price: "125.00" })]}
        filter="all"
        onFilterChange={() => {}}
        onSelectLine={() => {}}
      />
    );
    expect(screen.getByText("0.0%")).toBeInTheDocument();
  });

  it("filters to only the lines needing attention", () => {
    const onFilterChange = vi.fn();
    render(
      <DemoAnalysisTable
        lines={[
          line({ public_id: "l1", old_description: "Needs a look", match_status: "review_required" }),
          line({ public_id: "l2", old_description: "All good", match_status: "matched", risk_classification: "low" }),
        ]}
        filter="needs_attention"
        onFilterChange={onFilterChange}
        onSelectLine={() => {}}
      />
    );
    expect(screen.getByText("Needs a look")).toBeInTheDocument();
    expect(screen.queryByText("All good")).not.toBeInTheDocument();
  });

  it("shows an empty state rather than a blank table when no line matches the filter", () => {
    render(
      <DemoAnalysisTable
        lines={[line({ public_id: "l1", match_status: "matched", risk_classification: "low" })]}
        filter="unknown"
        onFilterChange={() => {}}
        onSelectLine={() => {}}
      />
    );
    expect(screen.getByText("No lines match this filter.")).toBeInTheDocument();
  });
});
