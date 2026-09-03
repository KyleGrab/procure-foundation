"""
Multi-stage product matching pipeline (spec Section 8/14). Everything in this package is pure
Python - no DB, no web framework - by design, so it can be unit tested (and, in this sandbox
with no network access to install rapidfuzz/pytest, actually RUN with stdlib unittest) without
any of the infrastructure the rest of the app needs. See docs/phase2-price-review-plan.md for
what's genuinely verified vs. syntax-checked in this delivery.
"""
