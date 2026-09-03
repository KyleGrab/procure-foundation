"""
Orchestrates stages 1-5 into a single confidence score + method + status per candidate pair,
and finds the best candidate for each old-list item across all new-list items (spec Section 8-9).
Stages 6 (embeddings) and 7 (LLM-assisted) are deferred to Phase 6 per docs/architecture.md's
AI sequencing - unresolved items fall through to REVIEW_REQUIRED rather than silently guessing,
which is the explicit instruction in spec Section 8 ("never allow AI to silently merge").
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.matching.exact_matcher import (
    match_by_barcode,
    match_by_exact_normalized_description,
    match_by_sku,
)
from app.matching.fuzzy_matcher import combined_description_score
from app.matching.normalize import find_variant_group, normalize_description

AUTO_MATCH_THRESHOLD = 0.95
REVIEW_RECOMMENDED_THRESHOLD = 0.80
# Below this, the "best" candidate isn't a plausible match at all - it's just the least-bad
# option among unrelated products (this showed up for real running the pipeline against
# synthetic data: discontinued items were being force-matched onto same-category, same-pack
# products purely on token overlap). Below the floor, the item is presented as having no
# candidate rather than a low-confidence proposal - the human still decides new-vs-discontinued
# vs-mis-mapped (spec Section 10's "Mark as New Product / Mark as Discontinued" actions), but the
# system stops pretending a bad guess is a starting point worth reviewing.
NO_PLAUSIBLE_MATCH_FLOOR = 0.45
# Score applied when descriptions otherwise look similar but belong to conflicting variant
# groups (spec Section 41 - "Cheddar Mature" must not auto-match "Cheddar Mild"). Capped well
# below REVIEW_RECOMMENDED_THRESHOLD so a conflicting-variant pair always lands in manual
# review, never auto-matches, regardless of how similar the rest of the string is.
VARIANT_CONFLICT_SCORE_CAP = 0.55


class MatchMethod(str, Enum):
    SKU = "exact_sku"
    BARCODE = "exact_barcode"
    EXACT_DESCRIPTION = "exact_normalized_description"
    FUZZY = "fuzzy_description"
    UNMATCHED = "unmatched"


class MatchStatus(str, Enum):
    AUTO_MATCHED = "auto_matched"
    REVIEW_RECOMMENDED = "review_recommended"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    NO_CANDIDATE = "no_candidate"


@dataclass(frozen=True)
class CandidateItem:
    key: str                 # caller-assigned identifier (e.g. row number) for traceability
    supplier_sku: str | None
    barcode: str | None
    description: str


@dataclass(frozen=True)
class MatchResult:
    old_key: str
    new_key: str | None
    confidence: float
    method: MatchMethod
    status: MatchStatus


def has_conflicting_variant(desc_a: str, desc_b: str) -> bool:
    group_a = find_variant_group(normalize_description(desc_a))
    group_b = find_variant_group(normalize_description(desc_b))
    return group_a is not None and group_b is not None and group_a != group_b


def score_pair(old_item: CandidateItem, new_item: CandidateItem) -> tuple[float, MatchMethod]:
    if match_by_sku(old_item.supplier_sku, new_item.supplier_sku):
        return 1.0, MatchMethod.SKU
    if match_by_barcode(old_item.barcode, new_item.barcode):
        return 1.0, MatchMethod.BARCODE
    if match_by_exact_normalized_description(old_item.description, new_item.description):
        return 0.98, MatchMethod.EXACT_DESCRIPTION

    score = combined_description_score(old_item.description, new_item.description)
    if has_conflicting_variant(old_item.description, new_item.description):
        score = min(score, VARIANT_CONFLICT_SCORE_CAP)
    return score, MatchMethod.FUZZY


def classify_status(confidence: float) -> MatchStatus:
    if confidence >= AUTO_MATCH_THRESHOLD:
        return MatchStatus.AUTO_MATCHED
    if confidence >= REVIEW_RECOMMENDED_THRESHOLD:
        return MatchStatus.REVIEW_RECOMMENDED
    return MatchStatus.MANUAL_REVIEW_REQUIRED


def find_best_match(old_item: CandidateItem, new_items: list[CandidateItem]) -> MatchResult:
    best_score = -1.0
    best_method = MatchMethod.UNMATCHED
    best_key: str | None = None

    for new_item in new_items:
        score, method = score_pair(old_item, new_item)
        if score > best_score:
            best_score, best_method, best_key = score, method, new_item.key

    if best_key is None or best_score < NO_PLAUSIBLE_MATCH_FLOOR:
        return MatchResult(old_item.key, None, 0.0, MatchMethod.UNMATCHED, MatchStatus.NO_CANDIDATE)

    return MatchResult(old_item.key, best_key, best_score, best_method, classify_status(best_score))
