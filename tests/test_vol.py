"""Realised volatility, shared by the low-vol signal and the allocator."""
import datetime as dt
import math

import pytest

from ghambla.store.store import Bar, FeatureStore
from ghambla.vol import annualised_vol, realised_vols


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def test_annualised_vol_matches_analytic_value():
    """Same analytic pin as the low-vol signal: alternating +x/-x log returns
    have mean zero, so sample sd is x * sqrt(n / (n - 1))."""
    x, n = 0.01, 100
    closes = [100.0]
    for i in range(n):
        closes.append(closes[-1] * math.exp(x if i % 2 == 0 else -x))
    expected = x * math.sqrt(n / (n - 1)) * math.sqrt(252)
    assert annualised_vol(closes) == pytest.approx(expected, rel=1e-9)


def test_constant_growth_has_zero_vol():
    assert annualised_vol([100.0 * 1.001 ** i for i in range(50)]) == pytest.approx(0.0, abs=1e-9)


def test_too_few_points_is_none():
    assert annualised_vol([100.0]) is None
    assert annualised_vol([]) is None


def test_non_positive_close_is_none():
    assert annualised_vol([100.0, 0.0, 100.0]) is None


def test_realised_vols_is_point_in_time(tmp_path):
    """Calm then violent; asked on the last calm day it must not see ahead."""
    store = FeatureStore(tmp_path / "v.db")
    try:
        calm = [100.0 * 1.001 ** i for i in range(60)]
        wild, px = [], calm[-1]
        for i in range(40):
            px *= 1.15 if i % 2 == 0 else 0.87
            wild.append(px)
        day = d("2025-01-01")
        bars = []
        for p in calm + wild:
            bars.append(Bar("TURN", day, p, p, p, p, p, 1000))
            day += dt.timedelta(days=1)
        store.upsert_bars(bars)

        last_calm = d("2025-01-01") + dt.timedelta(days=len(calm) - 1)
        after = d("2025-01-01") + dt.timedelta(days=len(calm) + len(wild) - 1)
        assert realised_vols(store, last_calm, ["TURN"], lookback=60)["TURN"] \
            == pytest.approx(0.0, abs=1e-6)
        assert realised_vols(store, after, ["TURN"], lookback=100)["TURN"] > 0.5
    finally:
        store.close()


def test_symbols_without_enough_history_are_absent(tmp_path):
    """Absent, not zero — a missing vol must not read as a risk-free asset."""
    store = FeatureStore(tmp_path / "v2.db")
    try:
        store.upsert_bars([Bar("THIN", d("2025-01-01"), 100.0, 100.0, 100.0,
                               100.0, 100.0, 1000)])
        assert realised_vols(store, d("2025-01-05"), ["THIN"], lookback=60) == {}
    finally:
        store.close()


def test_only_the_lookback_window_is_used(tmp_path):
    """Volatility must come from the configured window, not all of history.

    Violent for 200 days, then calm for 252. With a 252-day lookback the old
    violence sits outside the window and must not register. Caught by mutation
    testing: widening the store lookback passed every other test here.
    """
    store = FeatureStore(tmp_path / "window.db")
    try:
        wild, px = [], 100.0
        for i in range(200):
            px *= 1.15 if i % 2 == 0 else 0.87
            wild.append(px)
        calm = [px * (1.001 ** i) for i in range(252)]
        day = d("2025-01-01")
        bars = []
        for p in wild + calm:
            bars.append(Bar("SETTLED", day, p, p, p, p, p, 1000))
            day += dt.timedelta(days=1)
        store.upsert_bars(bars)

        last = d("2025-01-01") + dt.timedelta(days=len(wild) + len(calm) - 1)
        assert realised_vols(store, last, ["SETTLED"], lookback=252)["SETTLED"] \
            == pytest.approx(0.0, abs=1e-6)
    finally:
        store.close()
