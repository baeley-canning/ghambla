import pytest

from ghambla.costs import ibkr_tiered_commission


def test_per_share_rate_applies_on_large_orders():
    # 1000 shares @ $50: 1000 * 0.0035 = 3.50, well under the 1% cap of $500
    assert ibkr_tiered_commission(1000, 50.0) == pytest.approx(3.50)


def test_minimum_charge_applies_on_small_share_counts():
    # 10 shares @ $500 = $5000 notional. Per-share is $0.035, so the $0.35
    # minimum binds. The 1% cap ($50) is far away.
    assert ibkr_tiered_commission(10, 500.0) == pytest.approx(0.35)


def test_one_percent_cap_beats_the_minimum_on_tiny_trades():
    # THE case the NZ$100 live test depends on.
    # 1 share @ $30 = $30 notional. Minimum would be $0.35, but 1% is $0.30.
    # The cap wins, so the trade costs $0.30 not $0.35.
    assert ibkr_tiered_commission(1, 30.0) == pytest.approx(0.30)


def test_one_percent_cap_on_fractional_shares():
    # 0.5 shares @ $20 = $10 notional. Cap is $0.10.
    assert ibkr_tiered_commission(0.5, 20.0) == pytest.approx(0.10)


def test_zero_shares_costs_nothing():
    assert ibkr_tiered_commission(0, 100.0) == 0.0


def test_rejects_negative_inputs():
    with pytest.raises(ValueError):
        ibkr_tiered_commission(-1, 100.0)
    with pytest.raises(ValueError):
        ibkr_tiered_commission(1, -100.0)
