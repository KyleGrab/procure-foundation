"""
Description normalization for matching (spec Section 5). Deliberately conservative: the goal is
to remove formatting noise (case, punctuation, whitespace) so "COKE ZERO CAN 24 X 330ML" and
"Coke Zero 330ml x24" compare fairly at the token level - NOT to force them byte-identical.
Word-order and phrasing differences are handled by the fuzzy/token-overlap stages in scorer.py,
not here. This module must never erase variant information (see VARIANT_CONFLICT_GROUPS below,
used by scorer.py to stop "Cheddar Mature" from auto-matching "Cheddar Mild" - spec Section 41).
"""
from __future__ import annotations

import re

_PUNCTUATION_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")
# Inserts a boundary between digits and letters in either direction, so pack notation embedded
# in free-text descriptions tokenizes consistently regardless of which way round the supplier
# wrote it: "330ml" and "ml330" both become "330 ml", "x24" and "24x" both become "x 24" / "24 x".
# Without this, "24 X 330ML" and "330ml x24" (spec Section 5's own equivalence example) share
# almost no tokens even though they describe the same pack - see tests_pure/test_matching.py.
_DIGIT_LETTER_BOUNDARY_RE = re.compile(r"(?<=[0-9])(?=[a-zA-Z])|(?<=[a-zA-Z])(?=[0-9])")

# Words that carry no matching signal and only add noise to token-overlap scoring.
_STOPWORDS = {"the", "a", "an", "of", "and", "with", "in"}

# Pack-notation tokens (unit words and the multiplier "x") are common across many UNRELATED
# products that happen to share a pack size ("24 x 330ml" appears on dozens of different SKUs).
# Found by actually running the matcher against synthetic data (scripts/demo_price_review.py):
# unrelated products sharing only a pack size were scoring as near-duplicates because these
# tokens dominated the overlap calculation. Pack similarity is already handled separately and
# correctly by pack_parser.py / price normalization - it must not also leak into the
# product-*identity* signal used for token-overlap matching. See identity_tokens() below.
_PACK_NOISE_WORDS = {"x", "ml", "l", "kg", "g", "ea", "each", "unit", "units", "case", "of"}
_UNIT_LIKE_RE = re.compile(r"^\d+(\.\d+)?$")  # purely numeric tokens (pack quantities/sizes)

# Words that DO carry matching signal and must never be treated as equivalent to each other,
# even when overall string similarity is high. Each inner set is one group of mutually
# exclusive variants; a description containing a word from one group and a competing
# description containing a *different* word from the same group is a hard non-match candidate,
# not a fuzzy-match candidate - see scorer.py:has_conflicting_variant().
VARIANT_CONFLICT_GROUPS: list[set[str]] = [
    {"mature", "matured"},
    {"mild"},
    {"medium"},
    {"extra mature"},
    {"smooth"},
    {"original"},
    {"lite", "light"},
    {"zero", "sugar free", "no sugar"},
    {"diet"},
    {"full cream", "full-cream"},
    {"low fat", "fat free", "fatfree"},
    {"spicy", "hot"},
    {"unsalted"},
    {"salted"},
    {"smoked"},
    {"unsmoked"},
]


def normalize_description(raw: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace, drop stopwords. Idempotent."""
    if not raw:
        return ""
    text = raw.lower()
    text = _PUNCTUATION_RE.sub(" ", text)
    text = _DIGIT_LETTER_BOUNDARY_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    tokens = [t for t in text.split(" ") if t and t not in _STOPWORDS]
    return " ".join(tokens)


def tokenize(normalized: str) -> set[str]:
    return set(normalized.split(" ")) if normalized else set()


def identity_tokens(normalized: str) -> set[str]:
    """Token set with pack-notation noise removed - the token-overlap signal used to judge
    whether two descriptions refer to the *same product*, as distinct from whether they have the
    *same pack size* (a completely different, separately-handled question). See
    _PACK_NOISE_WORDS above for why this split exists."""
    tokens = tokenize(normalized)
    return {t for t in tokens if t not in _PACK_NOISE_WORDS and not _UNIT_LIKE_RE.match(t)}


def find_variant_group(normalized: str) -> set[str] | None:
    """Return the conflict group a description's tokens fall into, if any. A description can
    only sensibly belong to one group in this simple model - first match wins."""
    tokens = normalized.split(" ")
    joined = normalized
    for group in VARIANT_CONFLICT_GROUPS:
        for variant in group:
            if " " in variant:
                if variant in joined:
                    return group
            elif variant in tokens:
                return group
    return None
