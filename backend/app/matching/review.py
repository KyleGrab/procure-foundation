"""
Human-review bucketing (spec Section 10-11). Pure classification logic - the actual review
screen/decision persistence lives in services/price_review_service.py, since that needs the DB.
"""
from __future__ import annotations

from app.matching.scorer import MatchStatus


def requires_human_review(status: MatchStatus) -> bool:
    return status in (
        MatchStatus.REVIEW_RECOMMENDED,
        MatchStatus.MANUAL_REVIEW_REQUIRED,
        MatchStatus.NO_CANDIDATE,
    )


def is_authoritative(status: MatchStatus) -> bool:
    """Only an auto-match (or a human-confirmed one, tracked separately in the DB layer) is
    treated as authoritative for price-movement calculations - spec Section 10's "no uncertain
    match should be treated as authoritative until resolved.\""""
    return status == MatchStatus.AUTO_MATCHED
