# Compliance Review — ProcureIQ vs. UNIVERSAL_ENGINEERING_SPEC.md

Every finding below was checked against the actual code via `grep`/`view` before being written
down — none are inferred from memory of what was built. Per the spec's own §6.1/§6.3: this is
today's confirmed state, not an assumption carried forward from an earlier turn.

## Finding 1 (§2.5 — and more serious than a pure audit-trail gap): price-comparison basis can silently mix normalized and raw prices

`backend/app/services/price_review_service.py::calculate_line_movement`:

```python
cmp_old = line.old_normalized_price or line.old_price
cmp_new = line.new_normalized_price or line.new_price
```

Each side falls back to the raw price independently if pack-size normalization failed for that
side. If normalization succeeds for the old price but fails for the new one (or vice versa) —
plausible any time one side's pack-size string doesn't match `pack_parser.py`'s recognized
formats — `cmp_old` ends up as a normalized per-unit price (e.g., price per kg) while `cmp_new` is
a raw case price. `calculate_percentage_change` then computes a movement percentage from two
incompatible units, producing a number that looks like a normal, trustworthy price movement with
no signal anywhere that it isn't one.

This is worse than the spec's original §2.5 example (a resolved value indistinguishable from a
coincidental default) — that case produces a number that's *correct but unexplained*. This
produces a number that can be *actively wrong* with no error and no visible flag. It's the exact
failure category ADR pattern the spec's own §8 table calls "Boundary-condition matrix collapse"
crossed with "Indistinguishable fallback vs. coincidental match."

**Not proposing a fix yet, per this turn's scope** — but the shape of it: `PriceReviewLine` needs
a `comparison_basis` field (`both_normalized` / `both_raw` / `mixed_fallback`), and
`calculate_line_movement` should very likely refuse to compute a movement percentage at all in the
`mixed_fallback` case (raise/flag for manual review) rather than silently produce a number — same
posture as this codebase already takes for zero-old-price (`calculate_percentage_change` returns
`None`, never a fabricated 0%). Whether "refuse" or "flag but still compute" is the right call is
a real product decision, not mine to make silently.

## Finding 2 (§2.7): `entry_source` values are bare string literals, duplicated with no shared constant

```
app/services/rebate_service.py:99,108        "manual"
app/services/rebate_aggregation_service.py:58,60,64,67,69   "invoice_aggregation" (×4), "transaction_aggregation"
app/db/models/rebate.py:64                    default="manual"
```

Six occurrences across three files, comparing and assigning `entry_source` values that determine
ADR-014's rebate-source waterfall precedence — the exact scenario the spec's §2.7 example
describes almost verbatim (a lens-mode string hardcoded nine times before consolidation). A typo
in any one of these (`"invoice_aggregated"` vs `"invoice_aggregation"`) would silently break the
precedence logic — the `==` comparison just evaluates `False` and falls through to a worse data
source, with no exception raised anywhere.

`PriceReviewLine.match_status` (`"matched"`/`"new_product"`/`"discontinued"`/`"review_required"`/
`"ignored"`) has the same shape of gap: 16 literal occurrences across
`price_review_service.py`/`price_reviews.py`, no shared constant. Lower risk than `entry_source`
(this one doesn't drive a financial-calculation branch, "just" a workflow-status comparison), but
the same category of gap.

`RebateType`, `RebateStatus`, `ContractStatus`, `EscalationType`, `ABCClass` are **already**
proper Python `Enum` classes (`app/analytics/*.py`) — this pattern exists correctly elsewhere in
the codebase, it just wasn't applied consistently to `entry_source`/`match_status` when those
fields were added.

## Finding 3 (§4.2): percentage-rate fields accept any `Decimal`, unclamped

```python
# app/schemas/rebate.py
rate_pct: Decimal                    # RebateBandInput - no bound
flat_rate_pct: Decimal | None = None # RebateAgreementCreate - no bound

# app/schemas/contract.py
escalation_rate_pct: Decimal | None = None  # no bound
```

Presence is validated (the `model_validator`s correctly require these fields when the
`rebate_type`/`escalation_type` needs them), but magnitude isn't. A `rate_pct` of `-5` or `50`
(-500% or 5000%) currently passes validation and would silently produce a nonsensical calculated
rebate/escalation amount rather than a rejected request. Smaller, related gap: `currency` fields
are declared `str` with no allow-list across all nine schemas that have one (`contract.py`,
`price_review.py`, `purchase_invoice.py`, `purchase_order.py`, `rebate.py`, `supplier.py`,
`organization.py`) — any 3-character string currently passes.

## What's already compliant (checked, not assumed)

- Every quantity field this session added deliberately (`PurchaseOrderLineInput.quantity_ordered`,
  `unit_price`; `GoodsReceiptLineInput.quantity_received`) already uses `Field(ge=0)`.
- `RebateAgreementCreate.rebate_type`/`period_type`, `ContractCreate.escalation_type`,
  `OpportunityCreate.savings_type`/`baseline_methodology`/`confidence` all use `Field(pattern=...)`
  allow-lists — the §4.2 discipline is applied correctly for enum-shaped string fields, just not
  yet for numeric-range fields or free-text `currency`.
- Provenance tracking (§2.5) for the *other* fallback-cascade case in this codebase —
  `annual_quantity`/`quantity_source`/`quantity_confidence` on `PriceReviewLine` (ADR-008) and
  `entry_source` itself on `RebatePeriodActual` (ADR-012/013/014) — is correctly implemented.
  Finding 1 above is a *different, unflagged* fallback the existing provenance work didn't cover.
