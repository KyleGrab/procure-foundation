"""
Multi-currency treasury risk: FX exposure on foreign-currency-denominated transactions. Pure
Decimal logic - no DB, no framework, §2.1.

The unrealized-variance math here is structurally identical to
app.analytics.management_accounting.calculate_future_replacement_exposure's formula (a holding
gain/loss = (current_rate - booked_rate) x exposure_amount) - deliberately NOT reused, same
precedent as this codebase's RebateBand/TieredEscalationBand distinction: same arithmetic shape,
genuinely different domain (currency risk vs. commodity cost risk). Forcing FX exposure through a
replacement-cost-named function would be a worse fit than the small amount of duplicated
arithmetic this costs.

The core structural guard this module exists to enforce: an FEC (Forward Exchange Contract)
NEUTRALIZES spot exposure for the transaction it covers. Computing both an "unrealized variance"
(spot-based) AND a "hedging gain/loss" (FEC-based) for the same transaction would double-count
the exact same underlying currency risk once as unrealized and once as hedged - the two are
mutually exclusive by construction here, not just by convention.
"""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

CURRENCY_QUANTIZE = Decimal("0.0001")


def round_currency(value: Decimal) -> Decimal:
    return value.quantize(CURRENCY_QUANTIZE, rounding=ROUND_HALF_EVEN)


def calculate_fx_transaction_exposure(
    foreign_currency_amount: Decimal, transaction_date_spot_rate: Decimal, reporting_date_spot_rate: Decimal,
    fec_contract_rate: Decimal | None = None,
) -> dict:
    """
    Unhedged (fec_contract_rate is None):
        unrealized_variance = (reporting_date_spot_rate - transaction_date_spot_rate) * foreign_currency_amount
        Positive = adverse for an importer (the local currency has weakened since booking, so
        the same foreign-currency liability now costs more in ZAR). Never floored at zero - a
        favourable movement is a real, useful signal, same discipline as every other holding-
        variance calculation in this codebase. hedging_gain_loss is None.

    Hedged (fec_contract_rate provided):
        hedging_gain_loss = (reporting_date_spot_rate - fec_contract_rate) * foreign_currency_amount
        The value of having hedged, relative to what the unhedged spot exposure would have cost.
        unrealized_variance is None - the FEC neutralizes spot exposure for this transaction, so
        computing a second, spot-based number here would double-count the same risk.

    Both rate differences are carried at full, unrounded precision into the multiplication - only
    the final Rand result is rounded (learned directly from a real bug two turns ago in this
    engagement: rounding an intermediate rate before multiplying leaked currency out of
    conservation in calculate_segregated_route_cost).

    transaction_date_spot_rate and reporting_date_spot_rate have no defaults and must be strictly
    positive (ValueError otherwise) - omitting either is a TypeError, never a fabricated
    benchmark like 1.0. fec_contract_rate, once provided, is held to the identical standard - not
    a looser rule just because the parameter itself is optional.

    Structurally has no field resembling cogs/net_margin/inventory_value/mac_control_total/dio/
    dpo/ccc (checked directly in tests_pure) - a treasury holding variance must never be mistaken
    for a realized operational figure once this reaches a dashboard or ledger.
    """
    if transaction_date_spot_rate <= 0:
        raise ValueError(f"transaction_date_spot_rate must be positive, got {transaction_date_spot_rate}")
    if reporting_date_spot_rate <= 0:
        raise ValueError(f"reporting_date_spot_rate must be positive, got {reporting_date_spot_rate}")
    if fec_contract_rate is not None and fec_contract_rate <= 0:
        raise ValueError(f"fec_contract_rate must be positive, got {fec_contract_rate}")

    if fec_contract_rate is not None:
        hedging_gain_loss = round_currency((reporting_date_spot_rate - fec_contract_rate) * foreign_currency_amount)
        return {
            "is_hedged": True, "hedging_gain_loss": hedging_gain_loss, "unrealized_variance": None,
            "fec_contract_rate": fec_contract_rate,
        }

    unrealized_variance = round_currency(
        (reporting_date_spot_rate - transaction_date_spot_rate) * foreign_currency_amount
    )
    return {
        "is_hedged": False, "hedging_gain_loss": None, "unrealized_variance": unrealized_variance,
        "fec_contract_rate": None,
    }
