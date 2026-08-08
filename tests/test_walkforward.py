"""Walk-forward evaluation tests.

These pin the harness itself: window splitting, the untouched-holdout seam,
the pre-registered verdict, and honest handling of insufficient data. They use
stub signals against a seeded store, so they run fast and offline.
"""
import datetime as dt

import pytest

from ghambla.signals.base import Score
from ghambla.store.store import Bar, FeatureStore
from ghambla.walkforward import (
    HOLDOUT_FRAC_DEFAULT,
    WindowVerdict,
    calendar_windows,
    format_walk_forward,
    run_walk_forward,
    verdict,
)


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _seed(db_path, start="2018-01-01", n_days=1000, n_names=5):
    """Stable market: AAA drifts up, everyone else is flat. SPY is flat.

    Returns the open store; callers close it in a finally block.
    """
    s = FeatureStore(db_path)
    day = d(start)
    bars = []
    for i in range(n_days):
        bars.append(Bar("AAA", day, 100.0 + i, 100.0 + i, 100.0 + i,
                        100.0 + i, 100.0 + i, 1000))
        for sym, px in (("BBB", 50.0), ("CCC", 25.0), ("DDD", 10.0)):
            bars.append(Bar(sym, day, px, px, px, px, px, 1000))
        bars.append(Bar("SPY", day, 100.0, 100.0, 100.0, 100.0, 100.0, 1000))
        day += dt.timedelta(days=1)
    s.upsert_bars(bars)
    s.set_universe(d("2017-12-01"), ["AAA", "BBB", "CCC", "DDD"])
    return s


class LikesAAA:
    """Signal that always prefers AAA, so it makes money in the seeded store."""
    name = "likes_aaa"

    def score(self, store, as_of, universe):
        return {sym: Score(value=1.0 if sym == "AAA" else 0.0,
                           confidence=1.0, rationale="stub") for sym in universe}


class HatesAAA:
    """Signal that avoids AAA, so it loses in the seeded store."""
    name = "hates_aaa"

    def score(self, store, as_of, universe):
        return {sym: Score(value=-1.0 if sym == "AAA" else 0.0,
                           confidence=1.0, rationale="stub") for sym in universe}


def _wf(store, signal, **kw):
    return run_walk_forward(store, signal, d("2018-01-01"),
                            store.trading_dates(d("2018-01-01"), d("2020-12-31"))[-1],
                            **kw)


# --- window splitting ---

def test_calendar_windows_are_contiguous_and_non_overlapping():
    windows = calendar_windows(d("2018-01-01"), d("2018-12-31"), 4)
    assert len(windows) == 4
    assert windows[0][0] == d("2018-01-01")
    assert windows[-1][1] == d("2018-12-31")
    for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
        assert next_start > prev_end


def test_calendar_windows_reject_non_positive_counts():
    with pytest.raises(ValueError):
        calendar_windows(d("2018-01-01"), d("2018-12-31"), 0)


def test_calendar_windows_reject_reversed_range():
    with pytest.raises(ValueError):
        calendar_windows(d("2019-01-01"), d("2018-01-01"), 4)


# --- run shape ---

def test_research_windows_and_one_holdout(tmp_path):
    store = _seed(tmp_path / "w.db")
    try:
        r = _wf(store, LikesAAA(), n_windows=3, holdout_frac=0.2)
        assert len(r.research) == 3
        assert len(r.holdout) == 1
        assert r.holdout[0].kind == "holdout"
    finally:
        store.close()


def test_research_windows_never_overlap_the_holdout(tmp_path):
    """The seam: no research window may touch a holdout date."""
    store = _seed(tmp_path / "w.db")
    try:
        r = _wf(store, LikesAAA(), n_windows=4)
        h = r.holdout[0]
        for w in r.research:
            assert w.end < h.start
    finally:
        store.close()


def test_signal_name_and_period_are_carried(tmp_path):
    store = _seed(tmp_path / "w.db")
    try:
        r = _wf(store, LikesAAA(), n_windows=2)
        assert r.signal_name == "likes_aaa"
        assert r.start == d("2018-01-01")
    finally:
        store.close()


# --- verdict ---

def test_holdout_default_is_20_percent():
    assert HOLDOUT_FRAC_DEFAULT == 0.20


def test_all_windows_passing_passes():
    # Build a fake result by hand: everything passes.
    from ghambla.evaluate import Metrics
    good = WindowVerdict("research", d("2018-01-01"), d("2018-06-30"),
                         strategy=Metrics(1.0, 1.0, 2.0, -0.1, 5),
                         benchmark=Metrics(0.5, 0.5, 1.0, -0.2, 1))
    hold = WindowVerdict("holdout", d("2019-07-01"), d("2020-12-31"),
                         strategy=Metrics(1.0, 1.0, 2.0, -0.1, 5),
                         benchmark=Metrics(0.5, 0.5, 1.0, -0.2, 1))
    from ghambla.walkforward import WalkForwardResult
    r = WalkForwardResult("x", d("2018-01-01"), d("2020-12-31"),
                          windows=[good, good, hold])
    ok, reasons = verdict(r)
    assert ok
    assert reasons == []


def test_two_of_four_is_not_a_majority():
    """Strict majority: 2/4 must fail, never pass."""
    from ghambla.evaluate import Metrics
    from ghambla.walkforward import WalkForwardResult
    good = WindowVerdict("research", d("2018-01-01"), d("2018-06-30"),
                         strategy=Metrics(1.0, 1.0, 2.0, -0.1, 5),
                         benchmark=Metrics(0.5, 0.5, 1.0, -0.2, 1))
    bad = WindowVerdict("research", d("2018-07-01"), d("2018-12-31"),
                        strategy=Metrics(0.5, 0.5, 0.5, -0.3, 5),
                        benchmark=Metrics(0.5, 0.5, 1.0, -0.2, 1))
    hold = WindowVerdict("holdout", d("2019-07-01"), d("2020-12-31"),
                         strategy=Metrics(1.0, 1.0, 2.0, -0.1, 5),
                         benchmark=Metrics(0.5, 0.5, 1.0, -0.2, 1))
    r = WalkForwardResult("x", d("2018-01-01"), d("2020-12-31"),
                          windows=[good, good, bad, bad, hold])
    ok, reasons = verdict(r)
    assert not ok
    assert any("2/4" in reason for reason in reasons)


def test_holdout_failure_fails_even_with_research_majority():
    from ghambla.evaluate import Metrics
    from ghambla.walkforward import WalkForwardResult
    good = WindowVerdict("research", d("2018-01-01"), d("2018-06-30"),
                         strategy=Metrics(1.0, 1.0, 2.0, -0.1, 5),
                         benchmark=Metrics(0.5, 0.5, 1.0, -0.2, 1))
    bad_hold = WindowVerdict("holdout", d("2019-07-01"), d("2020-12-31"),
                             strategy=Metrics(0.5, 0.5, 0.4, -0.3, 5),
                             benchmark=Metrics(0.5, 0.5, 1.0, -0.2, 1))
    r = WalkForwardResult("x", d("2018-01-01"), d("2020-12-31"),
                          windows=[good, good, good, bad_hold])
    ok, reasons = verdict(r)
    assert not ok
    assert any("holdout" in reason for reason in reasons)


def test_missing_holdout_fails():
    from ghambla.evaluate import Metrics
    from ghambla.walkforward import WalkForwardResult
    good = WindowVerdict("research", d("2018-01-01"), d("2018-06-30"),
                         strategy=Metrics(1.0, 1.0, 2.0, -0.1, 5),
                         benchmark=Metrics(0.5, 0.5, 1.0, -0.2, 1))
    r = WalkForwardResult("x", d("2018-01-01"), d("2020-12-31"), windows=[good])
    ok, reasons = verdict(r)
    assert not ok
    assert any("holdout" in reason for reason in reasons)


def test_window_with_insufficient_data_is_a_fail_not_a_pass():
    bad = WindowVerdict("research", d("2018-01-01"), d("2018-06-30"),
                        strategy=None, benchmark=None, note="insufficient data in window")
    assert not bad.passed
    assert bad.sharpe_edge == 0.0
    assert not bad.drawdown_ok


# --- end-to-end with seeded store ---

def test_losing_signal_fails_walk_forward(tmp_path):
    """A signal that avoids the only rising name should fail everywhere."""
    store = _seed(tmp_path / "w.db")
    try:
        result = _wf(store, HatesAAA(), n_windows=3, holdout_frac=0.2)
        assert not result.passed
        assert result.holdout[0].note == ""  # data was fine; it genuinely lost
    finally:
        store.close()


def test_format_includes_window_table_and_verdict(tmp_path):
    store = _seed(tmp_path / "w.db")
    try:
        result = _wf(store, HatesAAA(), n_windows=2, holdout_frac=0.2)
        text = format_walk_forward(result)
        assert "research" in text
        assert "holdout" in text
        assert "Gate 0 (walk-forward)" in text
        assert "FAIL" in text
    finally:
        store.close()


def test_rejects_invalid_holdout_fraction(tmp_path):
    store = _seed(tmp_path / "w.db")
    try:
        with pytest.raises(ValueError):
            _wf(store, LikesAAA(), holdout_frac=0.0)
        with pytest.raises(ValueError):
            _wf(store, LikesAAA(), holdout_frac=1.0)
    finally:
        store.close()