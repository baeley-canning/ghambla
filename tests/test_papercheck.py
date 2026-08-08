"""Gate 1 papercheck tests."""
import datetime as dt

import pytest

from ghambla.journal import Journal
from ghambla.papercheck import (
    GATE_1_MAX_CUMULATIVE_DIFF,
    GATE_1_MIN_CORRELATION,
    PaperCheckResult,
    _correlation,
    _daily_returns,
    format_papercheck,
    papercheck,
)
from ghambla.signals.base import Score
from ghambla.store.store import Bar, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _seed(db_path, n_days=60):
    """AAA drifts up; SPY flat. Enough for a short backtest."""
    s = FeatureStore(db_path)
    day = d("2026-01-01")
    bars = []
    for i in range(n_days):
        bars.append(Bar("AAA", day, 100.0 + i, 100.0 + i, 100.0 + i,
                        100.0 + i, 100.0 + i, 1000))
        bars.append(Bar("SPY", day, 100.0, 100.0, 100.0, 100.0, 100.0, 1000))
        day += dt.timedelta(days=1)
    s.upsert_bars(bars)
    s.set_universe(d("2025-12-01"), ["AAA"])
    return s


class LikesAAA:
    name = "likes_aaa"

    def score(self, store, as_of, universe):
        return {sym: Score(value=1.0 if sym == "AAA" else 0.0,
                           confidence=1.0, rationale="stub") for sym in universe}


def test_daily_returns_are_sequential_ratios():
    assert _daily_returns([100.0, 110.0, 121.0]) == pytest.approx([0.10, 0.10])


def test_correlation_of_identical_series_is_one():
    assert _correlation([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_correlation_of_inverse_series_is_minus_one():
    assert _correlation([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == pytest.approx(-1.0)


def test_correlation_of_short_series_is_zero():
    assert _correlation([1.0], [1.0]) == 0.0


def test_papercheck_insufficient_paper_cycles(tmp_path):
    store = _seed(tmp_path / "p.db")
    try:
        journal = Journal(tmp_path / "j.jsonl")
        result = papercheck(journal, store, LikesAAA(), d("2026-01-01"), d("2026-02-28"))
        assert result.note
        assert not result.passed
    finally:
        store.close()


def test_papercheck_aligns_on_common_dates(tmp_path):
    store = _seed(tmp_path / "p.db")
    try:
        journal = Journal(tmp_path / "j.jsonl")
        # Simulate two paper cycles whose equity matches the backtest exactly.
        from ghambla.backtest import run_backtest
        bt = run_backtest(store, LikesAAA(), d("2026-01-01"), d("2026-02-28"),
                          initial_cash=10_000.0, top_n=1, rebalance_every=1000)
        # Write paper records for the first three backtest dates with identical equity.
        from ghambla.cycle import DecisionRecord
        for i, day in enumerate(bt.dates[:3]):
            journal.append(DecisionRecord(
                as_of=day, cycle_started=dt.datetime.now(dt.UTC), mode="paper",
                universe_size=1, signal_scores={}, allocator="rank_average",
                targets={}, risk_vetoes=[], orders=[], fills=[],
                equity=bt.equity[i], cash=0.0, positions={}))
        result = papercheck(journal, store, LikesAAA(), d("2026-01-01"), d("2026-02-28"),
                            top_n=1, rebalance_every=1000)
        assert result.correlation == pytest.approx(1.0)
        assert result.cumulative_diff == pytest.approx(0.0)
        assert result.passed
    finally:
        store.close()


def test_format_reports_both_numbers_and_verdict():
    r = PaperCheckResult(correlation=0.95, cumulative_diff=0.01)
    text = format_papercheck(r)
    assert "correlation" in text
    assert "divergence" in text
    assert "PASS" in text


def test_format_fails_on_low_correlation():
    r = PaperCheckResult(correlation=0.5, cumulative_diff=0.01)
    assert "FAIL" in format_papercheck(r)


def test_format_fails_on_high_divergence():
    r = PaperCheckResult(correlation=0.95, cumulative_diff=0.10)
    assert "FAIL" in format_papercheck(r)


def test_format_insufficient_data_fails():
    r = PaperCheckResult(note="fewer than 2 paper cycles in range")
    assert "FAIL" in format_papercheck(r)


def test_gate_constants_match_the_spec():
    assert GATE_1_MIN_CORRELATION == 0.90
    assert GATE_1_MAX_CUMULATIVE_DIFF == 0.03