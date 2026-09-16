import { test } from "node:test";
import assert from "node:assert/strict";
import { classifyLineForInvestigation } from "./price-review-line-classification.ts";
import type { PriceReviewLine } from "../types/price-review.ts";

function baseLine(overrides: Partial<PriceReviewLine>): PriceReviewLine {
  return {
    public_id: "line-1",
    old_supplier_sku: null,
    old_description: null,
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

test("classifies an unmatched line as unknown", () => {
  assert.strictEqual(classifyLineForInvestigation(baseLine({ match_status: "unmatched" })), "unknown");
});

test("classifies a line still awaiting a match decision as needing attention", () => {
  assert.strictEqual(classifyLineForInvestigation(baseLine({ match_status: "review_required" })), "needs_attention");
});

test("classifies a confirmed match flagged critical as needing attention", () => {
  assert.strictEqual(
    classifyLineForInvestigation(baseLine({ match_status: "matched", risk_classification: "critical" })),
    "needs_attention",
  );
});

test("classifies a confirmed, low-risk match as matched", () => {
  assert.strictEqual(
    classifyLineForInvestigation(baseLine({ match_status: "matched", risk_classification: "low" })),
    "matched",
  );
});

test("unmatched takes priority over any risk_classification value", () => {
  assert.strictEqual(
    classifyLineForInvestigation(baseLine({ match_status: "unmatched", risk_classification: "critical" })),
    "unknown",
  );
});
