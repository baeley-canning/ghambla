"""Overnight gap reaction tests.

Direction is pre-registered as continuation: a gap up scores positive. Flipping
that sign is gap-fade, the opposite hypothesis and a separate candidate — and
every ordering test would still pass, which is why the sign is pinned here.
"""
import datetime as dt

import pytest

from ghambla.signals.gap import GapSignal, overnight_gap
from ghambla.store.store import Bar, FeatureStore


def bar(o, c, day, sym="AAA"):
    hi, lo = max(o, c) * 1.01, min(o, c) * 0.99
    return Bar(symbol=sym, date=day, open=o, high=hi, low=lo, close=c,
               adj_close=c, volume=1000)


# --- the helper -----------------------------------------------------------

def test_a_gap_up_is_positive():
    assert overnight_gap(100.0, 105.0) == pytest.approx(0.05)


def test_a_gap_down_is_negative():
    assert overnight_gap(100.0, 95.0) == pytest.approx(-0.05)


def test_no_gap_is_zero():
    assert overnight_gap(100.0, 100.0) == pytest.approx(0.0)


def test_non_positive_prices_are_unusable():
    """Bad data, not a gap of several thousand percent."""
    assert overnight_gap(0.0, 100.0) is None
    assert overnight_gap(100.0, 0.0) is None
    assert overnight_gap(-5.0, 100.0) is None


# --- the signal -----------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "g.db")
    yield s
    s.close()


def seed(store, sym, pairs, start="2026-08-01"):
    """`pairs` is a list of (open, close) per day."""
    day = dt.date.fromisoformat(start)
    rows = []
    for o, c in pairs:
        rows.append(bar(o, c, day, sym))
        day += dt.timedelta(days=1)
    store.upsert_bars(rows)
    return day - dt.timedelta(days=1)


FLAT = [(100.0, 100.0)] * 6


def test_a_gapping_up_name_outranks_a_gapping_down_name(store):
    up = [(100.0, 100.0), (103.0, 103.0), (106.0, 106.0),
          (109.0, 109.0), (112.0, 112.0), (115.0, 115.0)]
    down = [(100.0, 100.0), (97.0, 97.0), (94.0, 94.0),
            (91.0, 91.0), (88.0, 88.0), (85.0, 85.0)]
    last = seed(store, "UP", up)
    seed(store, "DOWN", down)
    scores = GapSignal().score(store, last, ["UP", "DOWN"])
    assert scores["UP"].value > 0
    assert scores["DOWN"].value < 0


def test_continuation_not_fade(store):
    """A gap up must score POSITIVE. Negative here is the fade hypothesis."""
    up = [(100.0, 100.0)] + [(100.0 * 1.03 ** i, 100.0 * 1.03 ** i) for i in range(1, 6)]
    last = seed(store, "UP", up)
    assert GapSignal().score(store, last, ["UP"])["UP"].value > 0


def test_a_name_that_never_gapped_abstains(store):
    """Abstention, not zero — a zero would rank it mid-pack among movers."""
    last = seed(store, "QUIET", FLAT)
    scores = GapSignal().score(store, last, ["QUIET"])
    assert scores["QUIET"].confidence == 0.0


def test_gaps_below_the_threshold_do_not_count(store):
    tiny = [(100.0, 100.0)] + [(100.0 + 0.1 * i, 100.0 + 0.1 * i) for i in range(1, 6)]
    last = seed(store, "TINY", tiny)
    assert GapSignal(min_gap=0.01).score(store, last, ["TINY"])["TINY"].confidence == 0.0


def test_a_large_genuine_gap_is_kept_not_filtered(store):
    """Stored prices are already split-adjusted, so a huge overnight move is
    real news — a trial failure, a collapsed acquisition — and it is the most
    informative observation the signal has. Filtering it would discard the
    strongest data and call it cleaning."""
    crash = [(100.0, 100.0), (50.0, 50.0), (50.0, 50.0),
             (50.0, 50.0), (50.0, 50.0), (50.0, 50.0)]
    last = seed(store, "CRASH", crash)
    got = GapSignal().score(store, last, ["CRASH"])["CRASH"]
    assert got.confidence == 1.0
    assert got.value == pytest.approx(-0.5)


def test_splits_create_no_gap_because_bars_are_adjusted(store):
    """Verified against real data: NVDA split 10-for-1 on 2024-06-10 and the
    stored bars run 120.89 close -> 120.37 open, no gap at all."""
    adjusted = [(120.0, 120.89), (120.37, 121.79), (121.77, 120.91),
                (123.06, 125.2), (129.39, 129.61), (129.96, 131.88)]
    last = seed(store, "NVDAISH", adjusted)
    got = GapSignal(min_gap=0.10).score(store, last, ["NVDAISH"])["NVDAISH"]
    assert got.confidence == 0.0, "an adjusted split must not read as a gap"


def test_insufficient_history_abstains(store):
    last = seed(store, "SHORT", [(100.0, 100.0), (103.0, 103.0)])
    assert GapSignal().score(store, last, ["SHORT"])["SHORT"].confidence == 0.0


def test_unknown_symbol_abstains(store):
    seed(store, "UP", FLAT)
    assert GapSignal().score(store, dt.date(2026, 8, 6), ["NOPE"])["NOPE"].confidence == 0.0


def test_value_is_the_mean_of_qualifying_gaps(store):
    # gaps: +5%, then flat (ignored), then +5%  -> mean +5%
    spec = [(100.0, 100.0), (105.0, 105.0), (105.0, 105.0),
            (110.25, 110.25), (110.25, 110.25), (110.25, 110.25)]
    last = seed(store, "M", spec)
    got = GapSignal().score(store, last, ["M"])["M"]
    assert got.value == pytest.approx(0.05, rel=1e-3)


def test_rationale_reports_the_count(store):
    up = [(100.0, 100.0)] + [(100.0 * 1.03 ** i, 100.0 * 1.03 ** i) for i in range(1, 6)]
    last = seed(store, "UP", up)
    assert "gap" in GapSignal().score(store, last, ["UP"])["UP"].rationale.lower()


def test_rejects_bad_parameters():
    with pytest.raises(ValueError):
        GapSignal(lookback_days=1)
    with pytest.raises(ValueError):
        GapSignal(min_gap=-0.01)


def test_signal_reads_only_point_in_time_bars(store):
    up = [(100.0, 100.0)] + [(100.0 * 1.03 ** i, 100.0 * 1.03 ** i) for i in range(1, 6)]
    seed(store, "UP", up)
    early = GapSignal().score(store, dt.date(2026, 8, 2), ["UP"])
    assert early["UP"].confidence == 0.0
