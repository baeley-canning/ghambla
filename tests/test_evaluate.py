import datetime as dt

import pytest

from ghambla.evaluate import compute_metrics, format_report


def days(n):
    return [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(n)]


def test_total_return_is_first_to_last():
    m = compute_metrics(days(3), [100.0, 110.0, 120.0], n_trades=2)
    assert m.total_return == pytest.approx(0.20)


def test_max_drawdown_measures_peak_to_trough():
    m = compute_metrics(days(5), [100.0, 120.0, 60.0, 80.0, 90.0], n_trades=0)
    assert m.max_drawdown == pytest.approx(-0.50)


def test_no_drawdown_on_a_monotonic_curve():
    m = compute_metrics(days(3), [100.0, 110.0, 120.0], n_trades=0)
    assert m.max_drawdown == pytest.approx(0.0)


def test_flat_curve_has_zero_sharpe_not_nan():
    m = compute_metrics(days(5), [100.0] * 5, n_trades=0)
    assert m.sharpe == 0.0


def test_single_point_curve_is_all_zeros():
    m = compute_metrics(days(1), [100.0], n_trades=0)
    assert m.total_return == 0.0
    assert m.sharpe == 0.0
    assert m.max_drawdown == 0.0


def test_empty_curve_is_all_zeros():
    m = compute_metrics([], [], n_trades=0)
    assert m.total_return == 0.0


def test_trade_count_is_carried_through():
    m = compute_metrics(days(3), [100.0, 105.0, 110.0], n_trades=7)
    assert m.n_trades == 7


def test_report_names_both_sides_and_the_verdict():
    strat = compute_metrics(days(3), [100.0, 105.0, 110.0], n_trades=4)
    bench = compute_metrics(days(3), [100.0, 102.0, 104.0], n_trades=1)
    text = format_report(strat, bench, "SPY")
    assert "SPY" in text
    assert "Sharpe" in text
    assert "Max drawdown" in text
    assert "Gate 0" in text


def test_gate_fails_when_strategy_loses_to_benchmark():
    strat = compute_metrics(days(5), [100.0, 90.0, 80.0, 70.0, 60.0], n_trades=4)
    bench = compute_metrics(days(5), [100.0, 102.0, 104.0, 106.0, 108.0], n_trades=1)
    assert "FAIL" in format_report(strat, bench, "SPY")


def test_gate_fails_on_worse_drawdown_even_with_better_sharpe():
    # Strategy ends higher but suffers a deeper trough than the benchmark.
    strat = compute_metrics(days(5), [100.0, 40.0, 60.0, 90.0, 150.0], n_trades=4)
    bench = compute_metrics(days(5), [100.0, 100.0, 100.0, 100.0, 101.0], n_trades=1)
    report = format_report(strat, bench, "SPY")
    assert "FAIL" in report


# --- Sharpe ---------------------------------------------------------------
#
# Gate 0 is decided on the Sharpe edge over SPY, so this is the single number
# that determines whether a strategy is allowed near money. A mutation battery
# inverted its sign and dropped its annualisation, and the whole suite stayed
# green. These pin the exact value.
#
# Worked by hand for equity [100, 102, 103.02, 105.0804, 106.131204]:
#   daily returns  = [0.02, 0.01, 0.02, 0.01]
#   mean           = 0.015
#   sample stdev   = sqrt(1e-4 / 3)      = 0.00577350
#   ratio          = 0.015 / 0.00577350  = 2.598076
#   annualised     = 2.598076 * sqrt(252) = 41.2456

RISING = [100.0, 102.0, 103.02, 105.0804, 106.131204]
FALLING = [100.0, 98.0, 97.02, 95.0796, 94.128804]
HAND_COMPUTED_SHARPE = 41.2456


def test_sharpe_matches_the_hand_computed_value():
    """Pins both the ratio and the sqrt(252) annualisation."""
    m = compute_metrics(days(len(RISING)), RISING, n_trades=0)
    assert m.sharpe == pytest.approx(HAND_COMPUTED_SHARPE, rel=1e-4)


def test_a_losing_curve_has_negative_sharpe():
    m = compute_metrics(days(len(FALLING)), FALLING, n_trades=0)
    assert m.sharpe == pytest.approx(-HAND_COMPUTED_SHARPE, rel=1e-4)
    assert m.sharpe < 0


def test_a_winning_curve_has_positive_sharpe():
    assert compute_metrics(days(len(RISING)), RISING, n_trades=0).sharpe > 0


def test_sharpe_is_annualised_not_daily():
    """Without sqrt(252) the figure would be ~2.6, not ~41. Every Gate 0
    threshold in this project is expressed in annualised terms."""
    m = compute_metrics(days(len(RISING)), RISING, n_trades=0)
    assert m.sharpe > 10.0


def _equity_from(returns, start=100.0):
    curve = [start]
    for r in returns:
        curve.append(curve[-1] * (1.0 + r))
    return curve


def test_more_volatility_for_the_same_drift_lowers_sharpe():
    """Sharpe is reward per unit of risk, so the choppier path must score worse
    even though both grind upward. A perfectly constant return has zero
    variance and is deliberately floored at 0.0, so 'calm' still has to wobble."""
    calm = _equity_from([0.010, 0.009, 0.010, 0.009])
    choppy = _equity_from([0.06, -0.05, 0.06, -0.05])
    calm_m = compute_metrics(days(len(calm)), calm, n_trades=0)
    choppy_m = compute_metrics(days(len(choppy)), choppy, n_trades=0)
    assert calm_m.sharpe > choppy_m.sharpe > 0
