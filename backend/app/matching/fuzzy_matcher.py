"""
Stage 4 (attribute/token matching) and stage 5 (fuzzy string matching) of the pipeline.

Fuzzy scoring uses stdlib difflib.SequenceMatcher rather than RapidFuzz, because RapidFuzz isn't
installable in this offline environment (see docs/phase2-price-review-plan.md Section 3/5).
difflib is slower and scores differently on the same inputs than RapidFuzz's Indel/token-sort
ratios - this is a documented, intentional stand-in, not a silent substitution. Swapping the
implementation of `fuzzy_ratio()` for a RapidFuzz call is a one-function change when the package
is installable; nothing else in this module should need to change.
"""
from __future__ import annotations

from difflib import SequenceMatcher

from app.matching.normalize import identity_tokens, normalize_description


def fuzzy_ratio(text_a: str, text_b: str) -> float:
    """0.0-1.0 similarity. Swap-out point for RapidFuzz - see module docstring."""
    if not text_a or not text_b:
        return 0.0
    return SequenceMatcher(None, text_a, text_b).ratio()


def token_overlap_ratio(text_a: str, text_b: str) -> float:
    """Jaccard similarity over *identity* tokens only (pack-notation words/numbers excluded -
    see normalize.identity_tokens). Using the full token set here was the bug that let unrelated
    products sharing a pack size score as near-duplicates - caught by actually running the
    matcher against synthetic data, not by the unit tests alone (see
    docs/phase2-price-review-plan.md's note on why this sandbox's real-data demo run matters)."""
    tokens_a, tokens_b = identity_tokens(text_a), identity_tokens(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def combined_description_score(old_desc: str, new_desc: str) -> float:
    """Blends character-level and token-level similarity so word-reordering (common when
    suppliers reformat a price list) doesn't tank an otherwise-obvious match."""
    norm_a, norm_b = normalize_description(old_desc), normalize_description(new_desc)
    char_score = fuzzy_ratio(norm_a, norm_b)
    token_score = token_overlap_ratio(norm_a, norm_b)
    return round(0.4 * char_score + 0.6 * token_score, 4)
