"""
Deterministic purchase-order/invoice/goods-receipt calculations (spec Sections 9, 16, 24, Phase
4c). Pure `Decimal`/stdlib - no DB, no network - same pattern as every other analytics module this
session. Purchase Price Variance here is not a new formula invented for this phase: it's the
literal implementation of docs/analytics-methodology.md §5, written in Phase 0 and unimplemented
until now.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum

CURRENCY_QUANTIZE = Decimal("0.0001")


def round_currency(value: Decimal) -> Decimal:
    return value.quantize(CURRENCY_QUANTIZE, rounding=ROUND_HALF_EVEN)


class ReferencePriceSource(str, Enum):
    """analytics-methodology.md §5: a PPV number with no stated baseline is not auditable - the
    source is always stored alongside the variance, never implied."""
    CONTRACT = "contract"
    BUDGET = "budget"
    LOWEST_AVAILABLE_SUPPLIER = "lowest_available_supplier"
    APPROVED_QUOTE = "approved_quote"


@dataclass(frozen=True)
class PriceVarianceResult:
    expected_cost: Decimal
    actual_cost: Decimal
    variance: Decimal
    variance_pct: Decimal | None  # None when expected_cost is zero - undefined, not 0% or an error


def calculate_purchase_price_variance(
    reference_price: Decimal, actual_price: Decimal, quantity: Decimal,
) -> PriceVarianceResult:
    """analytics-methodology.md §5's exact formula:
    expected_cost = reference_price * quantity
    actual_cost = invoice_price * quantity
    variance = actual_cost - expected_cost
    """
    expected_cost = round_currency(reference_price * quantity)
    actual_cost = round_currency(actual_price * quantity)
    variance = round_currency(actual_cost - expected_cost)
    variance_pct = None if expected_cost == 0 else round_currency(variance / expected_cost * 100) / Decimal(100)
    return PriceVarianceResult(expected_cost, actual_cost, variance, variance_pct)


def calculate_invoice_line_net_amount(
    quantity: Decimal, unit_price: Decimal, discount_pct: Decimal | None = None,
) -> Decimal:
    """Spec Section 9's invoice line fields: quantity, unit_price, discount, net_amount.
    net_amount is pre-tax (standard invoicing convention - tax is applied on top of net, tracked
    separately, never folded into this figure)."""
    gross = quantity * unit_price
    if discount_pct:
        gross = gross * (Decimal(1) - discount_pct)
    return round_currency(gross)


def calculate_invoice_line_total_incl_tax(net_amount: Decimal, tax_pct: Decimal | None) -> Decimal:
    if not tax_pct:
        return round_currency(net_amount)
    return round_currency(net_amount * (Decimal(1) + tax_pct))


class ReceiptStatus(str, Enum):
    COMPLETE = "complete"
    SHORT = "short"
    OVER = "over"


@dataclass(frozen=True)
class ReceiptVarianceResult:
    variance_quantity: Decimal
    variance_pct: Decimal | None
    status: ReceiptStatus


def calculate_receipt_variance(
    quantity_ordered: Decimal, quantity_received: Decimal,
) -> ReceiptVarianceResult:
    """Ordered-vs-delivered analysis (spec Section 9's goods_receipts requirement). A positive
    variance means more was received than ordered (OVER); negative means a shortfall (SHORT)."""
    if quantity_ordered < 0 or quantity_received < 0:
        raise ValueError("quantities cannot be negative")
    variance = quantity_received - quantity_ordered
    variance_pct = None if quantity_ordered == 0 else round_currency(variance / quantity_ordered * 100) / Decimal(100)
    if variance == 0:
        status = ReceiptStatus.COMPLETE
    elif variance < 0:
        status = ReceiptStatus.SHORT
    else:
        status = ReceiptStatus.OVER
    return ReceiptVarianceResult(variance, variance_pct, status)
