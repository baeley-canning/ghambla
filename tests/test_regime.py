"""Market-regime trend filter.

The parameterisation is the standard one from the tactical-allocation
literature (Faber 2007): price versus its 200-day simple moving average. It is
deliberately not tuned here — a threshold chosen by looking at this dataset
would be the curve-fitting this repository exists to catch.
"""
import datetime as dt

import pytest

from ghambla.regime import trend_filter
from ghambla.store.store import Bar, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def series(store, symbol, prices, start="2024-01-01"):
    day = d(start)
    bars = []
    for p in prices:
        bars.append(Bar(symbol, day, p, p, p, p, p, 1000))
        day += dt.timedelta(days=1)
    store.upsert_bars(bars)
    return day - dt.timedelta(days=1)


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "r.db")
    yield s
    s.close()


def test_rising_market_is_risk_on(store):
    last = series(store, "SPY", [100.0 * 1.001 ** i for i in range(260)])
    assert trend_filter(store, last, "SPY", lookback=200) is True


def test_falling_market_is_risk_off(store):
    last = series(store, "SPY", [100.0 * 0.999 ** i for i in range(260)])
    assert trend_filter(store, last, "SPY", lookback=200) is False


def test_price_exactly_at_the_average_counts_as_risk_on(store):
    """A flat market is not a downtrend; >= keeps the boundary deterministic."""
    last = series(store, "SPY", [100.0] * 260)
    assert trend_filter(store, last, "SPY", lookback=200) is True


def test_insufficient_history_is_unknown_not_a_guess(store):
    """None means 'cannot evaluate'. The caller fails closed on it."""
    last = series(store, "SPY", [100.0] * 50)
    assert trend_filter(store, last, "SPY", lookback=200) is None


def test_missing_symbol_is_unknown(store):
    series(store, "SPY", [100.0] * 260)
    assert trend_filter(store, d("2024-06-01"), "NOPE", lookback=200) is None


def test_is_point_in_time(store):
    """A crash after `as_of` must not flip an earlier day to risk-off."""
    up = [100.0 * 1.001 ** i for i in range(260)]
    crash = [up[-1] * 0.97 ** i for i in range(60)]
    series(store, "SPY", up + crash)
    day_before_crash = d("2024-01-01") + dt.timedelta(days=len(up) - 1)
    assert trend_filter(store, day_before_crash, "SPY", lookback=200) is True


def test_non_positive_lookback_is_rejected(store):
    """`bars_as_of(lookback=0)` returns nothing and the average divides by zero.

    Raised by the cold review. Rejecting loudly matches the rest of the
    codebase, which raises on a non-positive n rather than degrading.
    """
    series(store, "SPY", [100.0] * 260)
    with pytest.raises(ValueError, match="lookback"):
        trend_filter(store, d("2024-06-01"), "SPY", lookback=0)
