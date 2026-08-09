"""Short-term reversal: buy what fell, on the hypothesis that it bounces.

A genuinely different anomaly family from the six candidates already failed.
Momentum says winners keep winning over 12 months; short-term reversal says
losers bounce over days (Jegadeesh 1990, Lehmann 1990). They are opposites, and
the reversal effect is the one documented at this horizon.

Sign convention matters and is the thing most easily got backwards: the score is
the NEGATED recent return, so the biggest loser scores highest and the long-only
constructor buys it. A name that ROSE scores negative and is therefore not held,
which preserves the ability to sit in cash when nothing has fallen.
"""
import datetime as dt

import pytest

from ghambla.signals.reversal import ReversalSignal
from ghambla.store.store import Bar, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def series(store, symbol, prices, start="2026-01-01"):
    day = d(start)
    bars = []
    for p in prices:
        bars.append(Bar(symbol, day, p, p, p, p, p, 1000))
        day += dt.timedelta(days=1)
    store.upsert_bars(bars)
    return day - dt.timedelta(days=1)


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "rev.db")
    yield s
    s.close()


def test_the_biggest_loser_scores_highest(store):
    """This is the whole signal. If it inverts, the strategy is momentum."""
    series(store, "FELL", [100.0] * 10 + [90.0])
    series(store, "FLAT", [100.0] * 11)
    last = series(store, "ROSE", [100.0] * 10 + [110.0])
    scores = ReversalSignal(lookback_days=2).score(store, last, ["FELL", "FLAT", "ROSE"])
    assert scores["FELL"].value > scores["FLAT"].value > scores["ROSE"].value


def test_a_name_that_rose_scores_negative_so_it_is_not_bought(store):
    """Preserves the go-to-cash property: nothing fell, nothing is held."""
    last = series(store, "ROSE", [100.0] * 10 + [110.0])
    assert ReversalSignal(lookback_days=2).score(store, last, ["ROSE"])["ROSE"].value < 0


def test_score_is_the_negated_return(store):
    """Pin the arithmetic, not just the ordering."""
    last = series(store, "X", [100.0] * 10 + [95.0])
    got = ReversalSignal(lookback_days=2).score(store, last, ["X"])["X"]
    assert got.value == pytest.approx(0.05)          # fell 5% -> scores +0.05


def test_lookback_window_is_respected(store):
    """A crash outside the window must not register.

    Found by mutation testing on two earlier signals; carried forward.
    """
    last = series(store, "OLD", [100.0, 50.0] + [50.0] * 20)
    assert ReversalSignal(lookback_days=3).score(store, last, ["OLD"])["OLD"].value \
        == pytest.approx(0.0)


def test_insufficient_history_abstains(store):
    last = series(store, "THIN", [100.0, 99.0])
    assert ReversalSignal(lookback_days=10).score(store, last, ["THIN"])["THIN"].confidence == 0.0


def test_non_positive_price_abstains(store):
    last = series(store, "ZERO", [100.0, 0.0, 100.0, 100.0])
    assert ReversalSignal(lookback_days=3).score(store, last, ["ZERO"])["ZERO"].confidence == 0.0


def test_is_point_in_time(store):
    """A later crash must not change an earlier day's score."""
    series(store, "LATER", [100.0] * 10 + [40.0] * 5)
    on_day_ten = d("2026-01-01") + dt.timedelta(days=9)
    assert ReversalSignal(lookback_days=3).score(store, on_day_ten, ["LATER"])["LATER"].value \
        == pytest.approx(0.0)


def test_lookback_below_two_is_rejected():
    with pytest.raises(ValueError, match="lookback_days"):
        ReversalSignal(lookback_days=1)
