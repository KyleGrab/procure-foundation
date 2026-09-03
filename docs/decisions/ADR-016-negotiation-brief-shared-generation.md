# ADR-016: One negotiation-brief generator, two context builders, not two generators

**Status:** Accepted

**Context:** Phase 2 built `POST /price-reviews/{id}/negotiation-brief`, which already has a
fully generic LLM-calling function (`generate_brief`), prompt template, and Pydantic output
schema (`NegotiationBriefOutput`) - none of it price-review-specific. The request for a general
`/api/v1/ai/negotiation-brief` sourced from spend/price-variance/supplier data could have been
read as "build a new negotiation brief feature," which would mean two prompt templates, two
output schemas, and two LLM-calling code paths to keep in sync - exactly the kind of duplication
ADR-014 refactored away from for rebate aggregation.

**Decision:** only the context-assembly function is new
(`build_negotiation_brief_context_from_spend`, in `negotiation_brief_service.py` alongside the
existing price-review one) - same `NegotiationBriefContext` output shape, sourced from
`app.analytics.spend_analytics` instead of `PriceReviewLine` rows. Both routes call the same
`generate_brief()`. Adding a third data source later (e.g. contract-linked briefs) means one more
context builder, not a third generator.

**Consequences:** the two routes' request/response shapes differ (one takes a price_review_id,
the other a supplier_id + optional date range) but their output is identical in structure, which
is correct - a negotiation brief is a negotiation brief regardless of what evidence assembled it,
and a caller consuming the response never needs to know which builder ran.
