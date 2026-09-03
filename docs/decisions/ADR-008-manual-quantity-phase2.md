# ADR-008: Manual annual-quantity entry for Phase 2 price review, not purchase-history ingestion

**Status:** Accepted

**Context:** The Phase 2 (Supplier Price Review) spec requires "historical purchasing volume"
linked to each matched product to compute annual financial impact, and explicitly names "manually
entered quantity" as a valid Low-confidence data source (its own Section 32). Building the full
`purchase_invoices` append-only ingestion pipeline (original master spec's Phase 3) just to
populate one field on a price-review line would be exactly the scope creep Phase 2's own
boundary section prohibits ("do not move into Phase 3 features unless strictly necessary").

**Decision:** `price_review_lines.annual_quantity` is entered manually by the buyer in this
phase, stored with `quantity_source = 'manual'` and `quantity_confidence = 'low'` per the spec's
own confidence tiers (Section 32). The schema (`historical_quantity`, `quantity_source`,
`quantity_confidence`) is shaped so that when Phase 3 (`purchase_invoices`) lands, swapping the
data source to real purchase history is a value change on existing columns, not a migration.

**Consequences:** Every annual-impact figure in this phase is only as reliable as what the buyer
typed in. The UI must make `quantity_confidence = low` visually unmissable on every derived
figure - this is a product requirement carried forward into the Phase 2 frontend work, not
optional polish. See `docs/phase2-price-review-plan.md` Section 2.2 and Section 5.
