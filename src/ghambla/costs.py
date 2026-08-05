"""IBKR Tiered commission model.

Tiered pricing is mandatory for this project rather than merely preferred.
Fixed pricing charges USD 1.00 minimum per order, which on a USD 30 position
is 3.3% each way. Tiered caps commission at 1% of trade value, so the same
trade costs USD 0.30. See the design doc, section 6.
"""

PER_SHARE = 0.0035
MIN_PER_ORDER = 0.35
MAX_FRACTION_OF_VALUE = 0.01


def ibkr_tiered_commission(shares: float, price: float) -> float:
    """Commission for one order, in USD.

    Exchange, regulatory and clearing fees are passed through by IBKR on top
    of this and are not modelled here; they are small relative to the spread
    assumption in the backtest.
    """
    if shares < 0 or price < 0:
        raise ValueError(f"shares and price must be non-negative, got {shares=} {price=}")
    if shares == 0 or price == 0:
        return 0.0

    notional = shares * price
    commission = max(PER_SHARE * shares, MIN_PER_ORDER)
    return min(commission, MAX_FRACTION_OF_VALUE * notional)
