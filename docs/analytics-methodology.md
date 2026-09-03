# ProcureIQ — Analytics Methodology (authoritative formulas)

Every formula below lives as a single, unit-tested function in `backend/app/analytics/`, called from
exactly one place. No dashboard, report, or AI-copilot response computes a financial figure inline — they
all call these functions and display the result. This file is the spec for those functions, not just
documentation of them; a PR that changes a formula changes this file in the same commit.

## 0. Precision & rounding rule (applies to everything below)

- Storage: `NUMERIC(18,4)` for currency, `NUMERIC(9,6)` for percentages/ratios.
- Python: `decimal.Decimal` exclusively — never `float` — for any value that touches these formulas.
- Rounding: `ROUND_HALF_EVEN` (banker's rounding), applied **once**, at the point a value is persisted or
  displayed — never mid-calculation. Intermediate values in a multi-step formula carry full precision.
- Every stored calculated value records: `algorithm_version`, `calculated_at`, `formula_name`, and a
  reference to its input rows (Section 104/105/106 of the spec — explainability and lineage are not optional
  add-ons, they're how "how was this calculated?" gets answered without a support ticket).

## 1. Price movement (supplier price review)

```
price_change            = new_price - old_price
price_change_pct        = price_change / old_price
annual_impact            = price_change * annual_quantity
```
`annual_quantity` is the trailing-12-month purchased quantity for that SKU from `purchase_invoice_lines`
(append-only fact table — see data-model.md), **not** a forecast. If pack sizes differ between old and new
list, normalize both to the same base unit (see Section 15 unit conversion) before comparing — comparing
R280/case to R14/kg is not a price change, it's a unit error.

## 2. Risk classification

Configurable per organisation via `organisation_settings` (not hardcoded), default bands:
`0–2% low, 2–5% medium, 5–10% high, 10%+ critical`. Combined with a weighted `financial_impact_score`:
```
financial_impact_score = normalize(annual_impact) * weight_spend
                        + normalize(price_change_pct) * weight_pct
                        + normalize(supplier_concentration) * weight_concentration
```
Weights are organisation-configurable, default `weight_spend=0.5, weight_pct=0.3, weight_concentration=0.2`.
`normalize()` is min-max scaling within the current price-review batch, documented and versioned — the point
is a R2 increase on a R4m-spend SKU should outrank a 20% increase on a R3,000 SKU, and the weights make that
explicit rather than implicit.

## 3. Gross margin impact

```
gross_profit             = selling_price - cost_price
gross_margin_pct         = gross_profit / selling_price
new_gross_profit         = selling_price - proposed_new_cost
new_gross_margin_pct     = new_gross_profit / selling_price
margin_pct_movement      = new_gross_margin_pct - gross_margin_pct
margin_value_impact      = (cost_price - proposed_new_cost) * annual_quantity * -1
```
Requires sales data joined at SKU+location level; where no selling price exists for a purchased SKU
(non-resale items, internal consumption), margin fields are `NULL`, not zero — zero would imply "no margin
impact," `NULL` correctly means "not applicable."

## 4. Required selling price for target margin

```
required_selling_price = cost / (1 - target_margin_pct)
```
`target_margin_pct` and whether `cost`/`selling_price` are tax-inclusive or -exclusive are both
organisation-level settings (`organisation_settings`), never assumed. VAT treatment must be explicit on
every price field it applies to (`price_basis` enum: `tax_inclusive` / `tax_exclusive`), not inferred.

## 5. Purchase price variance (PPV)

```
expected_cost   = reference_price * quantity     -- reference = contract / budget / approved-quote price
actual_cost     = invoice_price * quantity
variance        = actual_cost - expected_cost
```
`reference_price` source is explicit per calculation (`contract`, `budget`, `lowest_available_supplier`,
`approved_quote`) and stored alongside the variance — a PPV number with no stated baseline is not auditable.

## 6. Working capital (payment terms)

```
daily_spend              = annual_relevant_spend / 365
working_capital_release  = daily_spend * (proposed_terms_days - current_terms_days)
```
This is a **one-time cash-flow release**, reported separately from any recurring P&L saving, per Section 26
of the spec — the two must never be summed into a single "savings" figure on a dashboard. They answer
different questions (cash position vs. profitability) and combining them misleads whoever's reading the
number in a board pack.

## 7. Savings — five distinct types, never combined

`hard_saving | cost_avoidance | working_capital | margin_protection | efficiency_saving`

Each `opportunities` row has exactly one `savings_type`. A dashboard total across types must always be
labeled by type or shown as separate waterfall stages (Section 85), never as one blended "total savings"
number — that number is the fastest way to lose Finance's trust in the whole platform.

```
annual_saving = (baseline_unit_cost - new_unit_cost) * annual_quantity
```
`baseline_unit_cost` methodology is one of: `historic_average_price | prior_supplier_price | budget |
contract_price | approved_quotation` — stored on the opportunity record, not implied.

## 8. Rebates

```
tiered:      earned = Σ (spend_in_tier_i * tier_rate_i)   for each threshold band crossed
volume:      earned = total_qty * rate                     (flat) or per-tier as above
retrospective rebates recalculate earned_amount at period close against actual spend, not projected spend
rebate_leakage = expected_amount - received_amount
```
`expected_amount` is recalculated on each new invoice against threshold progress (drives the "approaching
threshold" alert in Section 29), `earned_amount` is fixed at period close, `received_amount` is only set from
an actual credit note / payment reference — never assumed equal to `earned_amount`.

## 9. Unit normalization (feeds §1 and §5)

Base units: mass → kg, volume → L, count → each. `pack_size × pack_quantity` converted to base unit before
any cross-supplier or cross-period price comparison. Conversion factors are a static, versioned lookup table
(`app/analytics/unit_conversions.py`), not inferred per-row — inferring "24x330ml" from free text is a
*matching* problem (Section 14), not a *conversion* problem, and the two must not be conflated in one
function.
