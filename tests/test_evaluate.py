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
