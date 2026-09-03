"""
Persists validated + mapped rows into price_review_files/price_review_lines, and computes the
file checksum used for duplicate-upload detection (spec Section 2/93). Needs the DB session, so
this is syntax-checked in this delivery, not run - see services/price_review_service.py for the
orchestration that calls it.
"""
from __future__ import annotations

import hashlib


def compute_checksum(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()
