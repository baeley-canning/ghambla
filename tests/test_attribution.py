"""Alpha, beta and information ratio.

These exist because Sharpe alone cannot distinguish "a real tilt penalised for
uncompensated variance" from "no skill at all". The project's momentum result
beat SPY on total return while losing on Sharpe, which is exactly the ambiguous
case. They are diagnostic: they explain a Gate 0 failure, they never move it.
"""
import datetime as dt

import pytest

from ghambla.evaluate import align_returns, attribution, format_attribution


def days(n, start=dt.date(2026, 1, 1)):
    return [start + dt.timedelta(days=i) for i in range(n)]


def curve(returns, start=100.0):
    out = [start]
    for r in returns:
        out.append(out[-1] * (1.0 + r))
    return out


# --- alignment ------------------------------------------------------------

def test_alignment_matches_on_dates_not_position():
    """Two backtests can skip different days. Zipping by index would compare
    Monday against Tuesday and silently report a fictional beta."""
    d = days(5)
    strat_dates = [d[0], d[1], d[2], d[3], d[4]]
    bench_dates = [d[0], d[2], d[3], d[4]]          # missing d[1]
    s, b = align_returns(strat_dates, curve([0.01, 0.02, 0.03, 0.04]),
                         bench_dates, curve([0.05, 0.06, 0.07]))
    assert len(s) == len(b)
    assert len(s) < 4


def test_alignment_of_identical_series():
    d = days(5)
    eq = curve([0.01, -0.01, 0.02, 0.0])
    s, b = align_returns(d, eq, d, eq)
    assert s == b
    assert len(s) == 4


def test_no_overlap_yields_nothing():
    s, b = align_returns(days(3), curve([0.01, 0.01]),
                         days(3, dt.date(2030, 1, 1)), curve([0.01, 0.01]))
    assert (s, b) == ([], [])


# --- beta -----------------------------------------------------------------

def test_beta_of_one_when_the_strategy_is_the_benchmark():
    d = days(30)
    eq = curve([0.01, -0.02, 0.03, -0.01] * 7 + [0.01, 0.0])
    a = attribution(d, eq, d, eq)
    assert a.beta == pytest.approx(1.0, rel=1e-6)
    assert a.alpha_annual == pytest.approx(0.0, abs=1e-9)


def test_beta_of_two_when_the_strategy_doubles_every_move():
    d = days(30)
    rets = [0.01, -0.02, 0.03, -0.01] * 7 + [0.01, 0.0]
    a = attribution(d, curve([2 * r for r in rets]), d, curve(rets))
    assert a.beta == pytest.approx(2.0, rel=0.05)


def test_beta_is_zero_when_the_benchmark_never_moves():
    """A flat benchmark has no variance to regress against, and dividing by
    rounding noise gives an arbitrary beta."""
    d = days(10)
    a = attribution(d, curve([0.01] * 9), d, [100.0] * 10)
    assert a.beta == 0.0


# --- alpha ----------------------------------------------------------------

def test_a_strategy_that_adds_a_constant_edge_has_positive_alpha():
    d = days(60)
    rets = [0.01, -0.015, 0.02, -0.005] * 14 + [0.01, 0.0, 0.005]
    strat = [r + 0.001 for r in rets]        # same moves, +10bp a day
    a = attribution(d, curve(strat), d, curve(rets))
    assert a.beta == pytest.approx(1.0, rel=0.05)
    assert a.alpha_annual > 0.15             # ~0.001 * 252


def test_a_lagging_strategy_has_negative_alpha():
    d = days(60)
    rets = [0.01, -0.015, 0.02, -0.005] * 14 + [0.01, 0.0, 0.005]
    strat = [r - 0.001 for r in rets]
    a = attribution(d, curve(strat), d, curve(rets))
    assert a.alpha_annual < 0


def test_leverage_alone_is_not_alpha():
    """A 2x levered benchmark earns more but adds no skill; alpha must stay
    near zero or the metric is just rewarding risk."""
    d = days(60)
    rets = [0.01, -0.015, 0.02, -0.005] * 14 + [0.01, 0.0, 0.005]
    a = attribution(d, curve([2 * r for r in rets]), d, curve(rets))
    assert abs(a.alpha_annual) < 0.05


# --- information ratio ----------------------------------------------------

def test_information_ratio_is_positive_for_a_consistent_outperformer():
    """The excess must vary. A perfectly constant daily edge has zero tracking
    error, which makes the ratio genuinely undefined rather than infinite —
    the code floors it at 0.0 and that is correct."""
    d = days(60)
    rets = [0.01, -0.015, 0.02, -0.005] * 14 + [0.01, 0.0, 0.005]
    excess = [0.0012 if i % 2 else 0.0008 for i in range(len(rets))]
    a = attribution(d, curve([r + e for r, e in zip(rets, excess)]), d, curve(rets))
    assert a.tracking_error > 0
    assert a.active_return > 0
    assert a.information_ratio > 0


def test_information_ratio_is_zero_when_tracking_is_perfect():
    d = days(30)
    eq = curve([0.01, -0.02, 0.03, -0.01] * 7 + [0.01, 0.0])
    a = attribution(d, eq, d, eq)
    assert a.tracking_error == pytest.approx(0.0, abs=1e-9)
    assert a.information_ratio == 0.0


def test_a_noisier_path_to_the_same_edge_scores_a_lower_ratio():
    """Same average outperformance, wildly different consistency. The whole
    point of the ratio is to separate those."""
    # An EVEN-length series, so the two alternating excess streams have exactly
    # the same mean. Only the tracking error differs, which is the whole claim.
    # With an odd length the means drift apart and the test can pass for the
    # wrong reason — it did, and a mutation that changed the denominator
    # survived because of it.
    rets = [0.01, -0.015, 0.02, -0.005] * 15
    d = days(len(rets) + 1)
    calm = [0.0012 if i % 2 else 0.0008 for i in range(len(rets))]
    wild = [0.031 if i % 2 else -0.029 for i in range(len(rets))]
    steady = attribution(d, curve([r + e for r, e in zip(rets, calm)]), d, curve(rets))
    noisy = attribution(d, curve([r + e for r, e in zip(rets, wild)]), d, curve(rets))

    assert steady.active_return == pytest.approx(noisy.active_return, rel=1e-9)
    assert noisy.tracking_error > steady.tracking_error
    assert steady.information_ratio > noisy.information_ratio > 0


# --- degenerate input -----------------------------------------------------

def test_too_few_points_returns_zeros_not_an_exception():
    a = attribution(days(2), [100.0, 101.0], days(2), [100.0, 100.5])
    assert a.beta == 0.0
    assert a.alpha_annual == 0.0
    assert a.information_ratio == 0.0


def test_empty_input_returns_zeros():
    a = attribution([], [], [], [])
    assert a.n_days == 0


# --- reporting ------------------------------------------------------------

def test_report_names_every_quantity():
    d = days(60)
    rets = [0.01, -0.015, 0.02, -0.005] * 14 + [0.01, 0.0, 0.005]
    text = format_attribution(attribution(d, curve([r + 0.001 for r in rets]),
                                          d, curve(rets)))
    for word in ("Beta", "alpha", "Information ratio", "Tracking error"):
        assert word in text
