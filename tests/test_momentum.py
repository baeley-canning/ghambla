import datetime as dt

import pytest

from ghambla.signals.momentum import MomentumSignal
from ghambla.store.store import Bar, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "mom.db")
    yield s
    s.close()


def make_series(store, symbol, start_price, daily_growth, n=300, start="2025-01-01"):
    day = d(start)
    price = start_price
    bars = []
    for _ in range(n):
        bars.append(Bar(symbol=symbol, date=day, open=price, high=price, low=price,
                        close=price, adj_close=price, volume=1000))
        price *= daily_growth
        day += dt.timedelta(days=1)
    store.upsert_bars(bars)
    return day - dt.timedelta(days=1)


def test_riser_scores_above_faller(store):
    last = make_series(store, "UP", 100.0, 1.002)
    make_series(store, "DOWN", 100.0, 0.998)
    scores = MomentumSignal().score(store, last, ["UP", "DOWN"])
    assert scores["UP"].value > scores["DOWN"].value


def test_flat_series_scores_near_zero(store):
    last = make_series(store, "FLAT", 100.0, 1.0)
    scores = MomentumSignal().score(store, last, ["FLAT"])
    assert scores["FLAT"].value == pytest.approx(0.0, abs=1e-9)


def test_insufficient_history_yields_zero_confidence(store):
    last = make_series(store, "SHORT", 100.0, 1.002, n=30)
    scores = MomentumSignal().score(store, last, ["SHORT"])
    assert scores["SHORT"].confidence == 0.0
    assert scores["SHORT"].value == 0.0


def test_unknown_symbol_yields_zero_confidence(store):
    make_series(store, "UP", 100.0, 1.002)
    scores = MomentumSignal().score(store, d("2025-06-01"), ["NOPE"])
    assert scores["NOPE"].confidence == 0.0


def test_skips_the_most_recent_month(store):
    """A stock that rose all year then crashed in the final month should still
    score positively, because the last `skip_days` are excluded."""
    day = d("2025-01-01")
    price = 100.0
    bars = []
    for i in range(300):
        price = price * 1.004 if i < 279 else price * 0.97
        bars.append(Bar(symbol="SPIKE", date=day, open=price, high=price, low=price,
                        close=price, adj_close=price, volume=1000))
        day += dt.timedelta(days=1)
    store.upsert_bars(bars)
    scores = MomentumSignal().score(store, day - dt.timedelta(days=1), ["SPIKE"])
    assert scores["SPIKE"].value > 0


def test_rationale_is_populated(store):
    last = make_series(store, "UP", 100.0, 1.002)
    scores = MomentumSignal().score(store, last, ["UP"])
    assert "momentum" in scores["UP"].rationale.lower()


def test_skip_days_must_be_smaller_than_lookback():
    with pytest.raises(ValueError):
        MomentumSignal(lookback_days=20, skip_days=20)
