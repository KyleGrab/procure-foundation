/**
 * Pure classification of a price review line into the four investigation buckets the demo
 * walkthrough filters by ("All" is the unfiltered view, not a bucket of its own). Deliberately
 * takes the same plain `PriceReviewLine` wire shape (types/price-review.ts) the real, live
 * matches/analysis pages already use - kept separate from any component so it's directly
 * unit-testable (mirrors backend spec §2.1's pure-logic boundary, applied here to a small piece
 * of frontend display logic rather than a calculation).
 */
import type { PriceReviewLine } from "@/types/price-review";

export type InvestigationCategory = "matched" | "needs_attention" | "unknown";

/**
 * Priority order (checked top to bottom, first match wins):
 * 1. No confirmed match on either side (match_status "unmatched") - genuinely unknown, nothing
 *    to show a confidence or price movement for.
 * 2. Still awaiting a human match decision (match_status "review_required") - the live
 *    /price-reviews/[id]/matches page's own review queue; a demo line here needs a look before
 *    its price movement means anything.
 * 3. A confirmed match the backend's own risk scoring flagged "critical" - matched, but still
 *    worth a buyer's attention before deciding.
 * 4. Everything else: a confirmed, low/medium-risk match.
 */
export function classifyLineForInvestigation(line: PriceReviewLine): InvestigationCategory {
  if (line.match_status === "unmatched") return "unknown";
  if (line.match_status === "review_required") return "needs_attention";
  if (line.risk_classification === "critical") return "needs_attention";
  return "matched";
}
