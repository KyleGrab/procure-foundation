# Phase 2 (this delivery) — Supplier Price Review: Implementation Plan

## 1. Inspection findings

Existing: `organisations`, `users`, `organisation_memberships`, `organisation_settings`, `audit_logs`,
`locations`, `refresh_tokens`. Auth, RBAC, RLS-backed tenant isolation, and the `procureiq_app` role
restrictions are in place and documented in `docs/security.md`. No `suppliers`, `products`, or price-review
tables exist yet — this document's "Phase 2" is a fresh vertical slice, not a continuation of anything
partially built.

## 2. Two reconciliations before writing code

### 2.1 Phase numbering

`docs/implementation-plan.md` (written for the original master spec) calls this work "Phase 4" and puts full
master-data CRUD (Phase 2) and full transactional-data ingestion (Phase 3) *before* it. This document calls
it "Phase 2" and explicitly forbids scope creep into broader master-data/transactional-data work. I'm
following **this** document's instruction — build only what the price-review workflow needs — and updating
`implementation-plan.md`'s phase table to reflect it actually happening in this order. The renumbering is
cosmetic; the sequencing decision (build the flagship feature as a vertical slice, not after two full
generic-data phases) is the real decision, and it's the right one — it's the only phase whose output is
commercially demonstrable on its own.

### 2.2 Historical purchase volume: manual entry now, not a purchase-ledger import

Section 13 says "where purchase history is available, link historical buying volume" and Section 32
explicitly names "manually entered quantity" as a valid (Low-confidence) data source. Building the full
`purchase_invoices` append-only ingestion pipeline (original spec Phase 3) just to populate one field on a
price-review line would be exactly the scope creep this document's boundary section prohibits.

**Decision:** `price_review_lines.annual_quantity` is manually entered by the buyer in this phase, stored
with `quantity_source = 'manual'` and `quantity_confidence = 'low'` per Section 32's own tiering. The
`historical_quantity`/`quantity_source`/`quantity_confidence` fields on the line are designed so that when
Phase 3 (transactional data / `purchase_invoices`) lands later, populating them from real purchase history
instead of manual entry is a data-source swap, not a schema change — `quantity_source` becomes
`'purchase_history'` and confidence upgrades to `medium`/`high` per the existing thresholds. Documented as
`ADR-008`.

### 2.3 Module layout: extending the Phase 1 layered convention, not the alternate package-per-feature one

This document's Section 37 suggests a `price_reviews/` package containing its own `models.py`/`schemas.py`/
`routes.py`/`service.py`. Phase 1 already established (and `docs/architecture.md` documents) a layered
convention: `db/models/`, `schemas/`, `services/`, `api/v1/` as shared top-level directories across all
features, matching the *original* master spec's repo structure (which this document is an addendum to, not
a replacement for). Running two different organizing principles side by side is the kind of inconsistency
that costs more later than it saves now.

**Decision:** keep the layered convention. `ingestion/` and `matching/` are built exactly as both documents
independently agree (both call for these as standalone packages), but price-review models, schemas, and
routes go into the existing `db/models/`, `schemas/`, `services/`, `api/v1/` directories, and calculations
go into `analytics/` per `docs/architecture.md` §1's rule that every financial number is produced by exactly
one function there.

## 3. What's genuinely testable in this sandbox (still no network)

`sqlalchemy`/`fastapi`/`pydantic`/`pytest`/`rapidfuzz` are still not installable here. But `openpyxl` **is**
already present, and everything in `matching/`, and `analytics/price_review_calculations.py` is pure
Python/`Decimal`/stdlib `re`/`difflib` by design — no DB, no web framework. That means normalization, pack
parsing, matching, and every financial formula in this phase can be written *and actually executed* against
real synthetic data in this session, using stdlib `unittest` — not just syntax-checked like Phase 1's DB/API
code. I'm doing that for the parts that carry financial and matching risk, and being explicit about what's
still unrun (DB models, migrations, FastAPI routes, the Excel export's integration with real review data,
the AI negotiation brief, which needs `LLM_API_KEY` and network).

`rapidfuzz` unavailable means the fuzzy-matching stage uses stdlib `difflib.SequenceMatcher` for now — noted
inline in the code as a swap-out, not hidden. Scores from `difflib` and RapidFuzz aren't numerically
identical, so the confidence thresholds (0.95 / 0.80) may need recalibrating against RapidFuzz once it's
installed — flagged as a real risk in Section 5.

## 4. Proposed migrations (0002)

`suppliers`, `price_reviews`, `price_review_files`, `price_review_mapping_templates`, `price_review_lines`,
`opportunities` — see `docs/data-model.md` addendum for full column lists. All tenant-scoped tables get the
same RLS treatment as Phase 1 (ADR-003) in the same migration, not a follow-up.

## 5. Technical risks

1. **Fuzzy-match threshold calibration is provisional.** difflib vs RapidFuzz score differently on the same
   string pairs; the 0.95/0.80 thresholds are the spec's numbers, not independently validated against
   difflib's distribution. Needs recalibration once RapidFuzz is installable, and before any auto-match
   result is trusted without a human reviewing a sample.
2. **Variant-conflict matching guard is a curated word list, not learned.** It correctly rejects the
   Section 41 test case (cheddar mature vs. mild) but will miss variant pairs not in the list. This is a
   known-incomplete heuristic, not a claim of general correctness — Stage 6/7 (embeddings, LLM-assisted) are
   the spec's own answer to this gap, deferred to Phase 6 per the original architecture.
3. **Manual quantity entry (§2.2) means "annual financial impact" is only as good as what the buyer typed
   in.** The UI must make `quantity_confidence = low` visually unmissable on every figure derived from it —
   this is a UX requirement, not just a data-model one.
4. **AI negotiation brief is architected, not verified.** No network in this environment means the
   `LLMProvider` → prompt → response path has never actually been called. Structure and guardrails (never
   invent market data, per Section 26) are in the prompt and the code path, not tested against a live model.
