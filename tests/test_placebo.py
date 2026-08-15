"""The placebo study.

Nine signals have failed the gate. Either they have no edge, or the gate
rejects almost everything and the failures say nothing. Running pure noise
through the identical gate is what separates those two readings.

The critical property tested here is that the placebo really is noise: if
RandomSignal ever reads the store, it stops being a placebo and the whole
measurement is void.
"""
import datetime as dt

import pytest

from ghambla.placebo import (
    PlaceboResult,
    PlaceboTrial,
    RandomSignal,
    format_placebo,
    run_placebo,
)
from ghambla.store.store import Bar, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


UNIVERSE = ["AAA", "BBB", "CCC", "DDD", "EEE"]


class ExplodingStore:
    """Any read at all fails the placebo's core premise."""

    def __getattr__(self, name):
        raise AssertionError(f"RandomSignal touched the store via .{name}()")


# --- the signal is genuinely noise ---------------------------------------

def test_random_signal_never_reads_the_store():
    """If it peeks at prices it is not a placebo, and the false-pass rate it
    produces would be meaningless."""
    RandomSignal(seed=1).score(ExplodingStore(), d("2026-01-05"), UNIVERSE)


def test_scores_every_symbol_with_full_confidence():
    got = RandomSignal(seed=1).score(ExplodingStore(), d("2026-01-05"), UNIVERSE)
    assert set(got) == set(UNIVERSE)
    assert all(s.confidence == 1.0 for s in got.values())


def test_scores_are_in_range():
    got = RandomSignal(seed=3).score(ExplodingStore(), d("2026-01-05"), UNIVERSE)
    assert all(-1.0 <= s.value <= 1.0 for s in got.values())


# --- reproducibility ------------------------------------------------------

def test_same_seed_and_date_gives_the_same_scores():
    """A surprising trial has to be re-runnable, or it cannot be investigated."""
    a = RandomSignal(seed=7).score(ExplodingStore(), d("2026-01-05"), UNIVERSE)
    b = RandomSignal(seed=7).score(ExplodingStore(), d("2026-01-05"), UNIVERSE)
    assert {k: v.value for k, v in a.items()} == {k: v.value for k, v in b.items()}


def test_different_seeds_give_different_scores():
    a = RandomSignal(seed=1).score(ExplodingStore(), d("2026-01-05"), UNIVERSE)
    b = RandomSignal(seed=2).score(ExplodingStore(), d("2026-01-05"), UNIVERSE)
    assert {k: v.value for k, v in a.items()} != {k: v.value for k, v in b.items()}


def test_scores_change_between_dates():
    a = RandomSignal(seed=1).score(ExplodingStore(), d("2026-01-05"), UNIVERSE)
    b = RandomSignal(seed=1).score(ExplodingStore(), d("2026-02-05"), UNIVERSE)
    assert {k: v.value for k, v in a.items()} != {k: v.value for k, v in b.items()}


def test_trials_do_not_depend_on_execution_order():
    """Global random state would make trial 5 depend on whether 1-4 ran."""
    first = RandomSignal(seed=9).score(ExplodingStore(), d("2026-01-05"), UNIVERSE)
    for other in range(20):
        RandomSignal(seed=other).score(ExplodingStore(), d("2026-03-01"), UNIVERSE)
    again = RandomSignal(seed=9).score(ExplodingStore(), d("2026-01-05"), UNIVERSE)
    assert {k: v.value for k, v in first.items()} == {k: v.value for k, v in again.items()}


# --- aggregation ----------------------------------------------------------

def trial(seed, passed, edge, gate):
    return PlaceboTrial(seed=seed, research_passed=passed, research_total=4,
                        holdout_edge=edge, holdout_passed=gate, gate_passed=gate)


def test_pass_rate():
    r = PlaceboResult(trials=[trial(0, 0, -0.2, False), trial(1, 3, 0.4, True),
                              trial(2, 1, 0.0, False), trial(3, 0, -0.5, False)])
    assert r.pass_rate == pytest.approx(0.25)


def test_pass_rate_of_no_trials_is_zero_not_a_crash():
    assert PlaceboResult(trials=[]).pass_rate == 0.0


def test_median_and_best_edge():
    r = PlaceboResult(trials=[trial(0, 0, -0.2, False), trial(1, 0, 0.4, False),
                              trial(2, 0, 0.0, False)])
    assert r.median_holdout_edge == pytest.approx(0.0)
    assert r.best_holdout_edge == pytest.approx(0.4)


# --- reporting ------------------------------------------------------------

def test_report_states_a_zero_rate_plainly():
    r = PlaceboResult(trials=[trial(i, 0, -0.3, False) for i in range(20)])
    text = format_placebo(r, gate_threshold=0.30)
    assert "0" in text
    assert "random" in text.lower()


def test_report_warns_when_the_gate_passes_noise_often():
    r = PlaceboResult(trials=[trial(i, 3, 0.5, i < 5) for i in range(20)])
    text = format_placebo(r, gate_threshold=0.30).lower()
    assert "noise" in text or "distinguish" in text


def test_report_counts_how_many_candidates_before_a_spurious_pass():
    r = PlaceboResult(trials=[trial(i, 2, 0.1, i < 1) for i in range(20)])
    assert format_placebo(r, gate_threshold=0.30)


# --- end to end -----------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "p.db")
    day = d("2024-01-01")
    bars = []
    for i in range(500):
        for k, sym in enumerate(UNIVERSE + ["SPY"]):
            px = 100.0 + i * (0.05 + 0.01 * k) + ((i * (k + 3)) % 7)
            bars.append(Bar(sym, day, px, px * 1.01, px * 0.99, px, px, 1000))
        day += dt.timedelta(days=1)
    s.upsert_bars(bars)
    s.set_universe(d("2023-01-01"), UNIVERSE)
    yield s
    s.close()


def test_run_placebo_produces_one_trial_per_seed(store):
    r = run_placebo(store, d("2024-02-01"), d("2025-03-01"),
                    trials=3, top_n=2, rebalance_every=21)
    assert len(r.trials) == 3
    assert [t.seed for t in r.trials] == [0, 1, 2]


def test_run_placebo_is_reproducible(store):
    a = run_placebo(store, d("2024-02-01"), d("2025-03-01"), trials=2, top_n=2)
    b = run_placebo(store, d("2024-02-01"), d("2025-03-01"), trials=2, top_n=2)
    assert [t.holdout_edge for t in a.trials] == [t.holdout_edge for t in b.trials]


def test_progress_is_reported(store):
    seen = []
    run_placebo(store, d("2024-02-01"), d("2025-03-01"), trials=2, top_n=2,
                on_progress=lambda done, total, t: seen.append((done, total)))
    assert seen == [(1, 2), (2, 2)]
