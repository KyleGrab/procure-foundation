/**
 * Static illustrative data for the /price-reviews/demo walkthrough (PROCUREIQ-PRICE-REVIEW-DEMO-UX-R2).
 * Everything below is fabricated for demonstration purposes only - a made-up supplier and SKUs,
 * not a real company, customer, or supplier ever seen by this system. It is never sent anywhere,
 * never persisted, and is typed against the exact same wire shapes (types/price-review.ts) the
 * real /price-reviews/[id]/* pages use against the live API, so this walkthrough exercises the
 * same rendering code paths (decimal-safe formatting, "—" for unknowns) a real review would.
 *
 * Numeric fields are Decimal strings, exactly as the backend would serialize them - never a JS
 * number - and every percentage_change/match_confidence value here is deliberately chosen with
 * at most 3 fractional digits so that decimal-display.ts's formatDecimalPercent (which truncates
 * rather than rounds, see its own docstring) renders them losslessly.
 */
import type { PriceReviewLine } from "@/types/price-review";

export interface DemoReviewOverview {
  public_id: string;
  supplier_public_id: string;
  supplier_name: string;
  status: string;
  status_label: string;
  received_at: string;
  effective_date: string;
  currency: string;
  line_count: number;
  next_action_label: string;
  next_action_href: string;
}

export const DEMO_REVIEW: DemoReviewOverview = {
  public_id: "demo-review-illustrative",
  supplier_public_id: "demo-supplier-illustrative",
  supplier_name: "Illustrative Supplier Co.",
  status: "in_analysis",
  status_label: "In analysis",
  received_at: "2026-09-08",
  effective_date: "2026-10-01",
  currency: "ZAR",
  line_count: 7,
  next_action_label: "Review the analysis",
  next_action_href: "/price-reviews/demo/analysis",
};

export const DEMO_LINES: PriceReviewLine[] = [
  {
    public_id: "demo-line-01",
    old_supplier_sku: "ISK-1042",
    old_description: "Illustrative Widget A, Case of 12",
    old_pack_raw: "12 x 1L",
    old_price: "184.50",
    new_supplier_sku: "ISK-1042",
    new_description: "Illustrative Widget A, Case of 12",
    new_pack_raw: "12 x 1L",
    new_price: "199.90",
    match_status: "matched",
    match_confidence: "0.970",
    movement_type: "price_increase",
    percentage_change: "0.083",
    annual_impact: "18480.00",
    risk_classification: "low",
    buyer_decision: null,
    target_price: null,
    potential_cost_avoidance: null,
  },
  {
    public_id: "demo-line-02",
    old_supplier_sku: "ISK-2071",
    old_description: "Illustrative Widget B, Bulk Drum",
    old_pack_raw: "1 x 25L",
    old_price: "520.00",
    new_supplier_sku: "ISK-2071",
    new_description: "Illustrative Widget B, Bulk Drum",
    new_pack_raw: "1 x 25L",
    new_price: "712.50",
    match_status: "matched",
    match_confidence: "0.910",
    movement_type: "price_increase",
    percentage_change: "0.370",
    annual_impact: "96330.00",
    risk_classification: "critical",
    buyer_decision: null,
    target_price: null,
    potential_cost_avoidance: null,
  },
  {
    public_id: "demo-line-03",
    old_supplier_sku: "ISK-3355",
    old_description: "Illustrative Widget C",
    old_pack_raw: "1 x 5L Drum",
    old_price: "310.00",
    new_supplier_sku: "ISK-3355-N",
    new_description: "Illustrative Widget C (repackaged)",
    new_pack_raw: "1 x 6L Drum",
    new_price: "335.00",
    match_status: "review_required",
    match_confidence: "0.540",
    movement_type: "pack_change",
    percentage_change: null,
    annual_impact: null,
    risk_classification: "medium",
    buyer_decision: null,
    target_price: null,
    potential_cost_avoidance: null,
  },
  {
    public_id: "demo-line-04",
    old_supplier_sku: "ISK-4108",
    old_description: "Illustrative Widget D, 2kg Bag",
    old_pack_raw: "1 x 2kg",
    old_price: "89.00",
    new_supplier_sku: null,
    new_description: null,
    new_pack_raw: null,
    new_price: null,
    match_status: "unmatched",
    match_confidence: null,
    movement_type: null,
    percentage_change: null,
    annual_impact: null,
    risk_classification: null,
    buyer_decision: null,
    target_price: null,
    potential_cost_avoidance: null,
  },
  {
    public_id: "demo-line-05",
    old_supplier_sku: "ISK-5217",
    old_description: "Illustrative Widget E, Case of 6",
    old_pack_raw: "6 x 2L",
    old_price: "310.00",
    new_supplier_sku: "ISK-5217",
    new_description: "Illustrative Widget E, Case of 6",
    new_pack_raw: "6 x 2L",
    new_price: "295.00",
    match_status: "matched",
    match_confidence: "0.990",
    movement_type: "price_decrease",
    percentage_change: "-0.048",
    annual_impact: "-14400.00",
    risk_classification: "low",
    buyer_decision: null,
    target_price: null,
    potential_cost_avoidance: "14400.00",
  },
  {
    public_id: "demo-line-06",
    old_supplier_sku: "ISK-6390",
    old_description: "Illustrative Widget F, Case of 24",
    old_pack_raw: "24 x 500ml",
    old_price: "125.00",
    new_supplier_sku: "ISK-6390",
    new_description: "Illustrative Widget F, Case of 24",
    new_pack_raw: "24 x 500ml",
    new_price: "125.00",
    match_status: "matched",
    match_confidence: "1.000",
    movement_type: "unchanged",
    percentage_change: "0",
    annual_impact: "0.00",
    risk_classification: "low",
    buyer_decision: null,
    target_price: null,
    potential_cost_avoidance: null,
  },
  {
    public_id: "demo-line-07",
    old_supplier_sku: null,
    old_description: null,
    old_pack_raw: null,
    old_price: null,
    new_supplier_sku: "ISK-7481",
    new_description: "Illustrative Widget G (new listing)",
    new_pack_raw: "1 x 10L",
    new_price: "410.00",
    match_status: "review_required",
    match_confidence: "0.300",
    movement_type: null,
    percentage_change: null,
    annual_impact: null,
    risk_classification: "medium",
    buyer_decision: null,
    target_price: null,
    potential_cost_avoidance: null,
  },
];

/** Fixed references into DEMO_LINES for the negotiation brief - looked up by id rather than
 * derived at render time by sorting/comparing amounts, so the brief never needs to run any
 * money-math over the demo data (see PROCUREIQ-PRICE-REVIEW-DEMO-UX-R2's "no float money math"
 * rule) to decide what to feature; it just names the lines this fixed, curated brief is about. */
export const DEMO_NEGOTIATION_FOCUS_LINE_IDS = ["demo-line-02", "demo-line-01", "demo-line-03"] as const;

export function findDemoLineById(publicId: string): PriceReviewLine | undefined {
  return DEMO_LINES.find((line) => line.public_id === publicId);
}
