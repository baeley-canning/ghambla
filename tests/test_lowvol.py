"""Low-volatility signal tests."""
import datetime as dt
import math

import pytest

from ghambla.signals.lowvol import LowVolSignal
from ghambla.store.store import Bar, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _seed(db_path):
    """CALM drifts steadily up (low vol); VOLATILE swings hard (high vol)."""
    s = FeatureStore(db_path)
    day = d("2025-01-01")
    bars = []
    p_calm, p_vol = 100.0, 100.0
    for i in range(300):
        # Calm: +0.2% every day. Volatile: alternating +10% / -8%.
        p_calm *= 1.002
        p_vol *= 1.10 if i % 2 == 0 else 0.92
        bars.append(Bar("CALM", day, p_calm, p_calm, p_calm, p_calm, p_calm, 1000))
        bars.append(Bar("VOL", day, p_vol, p_vol, p_vol, p_vol, p_vol, 1000))
        day += dt.timedelta(days=1)
    s.upsert_bars(bars)
    s.set_universe(d("2024-12-01"), ["CALM", "VOL"])
    return s


def test_calm_scores_above_volatile(tmp_path):
    store = _seed(tmp_path / "lv.db")
    try:
        last = store.trading_dates(d("2025-01-01"), d("2025-12-31"))[-1]
        scores = LowVolSignal().score(store, last, ["CALM", "VOL"])
        assert scores["CALM"].value > scores["VOL"].value
        assert scores["CALM"].confidence == 1.0
    finally:
        store.close()


def test_insufficient_history_yields_zero_confidence(tmp_path):
    store = _seed(tmp_path / "lv.db")
    try:
        scores = LowVolSignal().score(store, d("2025-01-10"), ["CALM", "VOL"])
        assert scores["CALM"].confidence == 0.0
    finally:
        store.close()


def test_flat_series_scores_above_swinging_series(tmp_path):
    s = FeatureStore(tmp_path / "flat.db")
    day = d("2025-01-01")
    bars = []
    for i in range(300):
        flat_px = 100.0 + i * 0.01  # tiny steady drift, ~zero vol
        bars.append(Bar("FLAT", day, flat_px, flat_px, flat_px, flat_px, flat_px, 1000))
        px = 100.0 if i % 2 == 0 else 200.0
        bars.append(Bar("SWING", day, px, px, px, px, px, 1000))
        day += dt.timedelta(days=1)
    s.upsert_bars(bars)
    s.set_universe(d("2024-12-01"), ["FLAT", "SWING"])
    try:
        last = s.trading_dates(d("2025-01-01"), d("2025-12-31"))[-1]
        scores = LowVolSignal().score(s, last, ["FLAT", "SWING"])
        assert scores["FLAT"].value > scores["SWING"].value
    finally:
        s.close()


def _write(store, symbol, prices, start="2025-01-01"):
    """Write `prices` as consecutive daily bars; returns the last bar's date."""
    day = d(start)
    bars = []
    for px in prices:
        bars.append(Bar(symbol, day, px, px, px, px, px, 1000))
        day += dt.timedelta(days=1)
    store.upsert_bars(bars)
    return day - dt.timedelta(days=1)


def test_annualised_volatility_matches_analytic_value(tmp_path):
    """Pin the arithmetic, not just the ordering.

    A series whose log returns alternate exactly +x, -x in equal number has
    mean zero, so its *sample* standard deviation is analytically
    x * sqrt(n / (n - 1)). Deriving the expectation that way — rather than by
    re-running the implementation's own loop — means this test fails if the
    annualisation factor is wrong, if population stdev is used instead of
    sample, or if simple returns are used instead of log returns. The
    ordering-only tests above pass under all three of those bugs.
    """
    x, n_returns = 0.01, 100
    prices = [100.0]
    for i in range(n_returns):
        prices.append(prices[-1] * math.exp(x if i % 2 == 0 else -x))

    store = FeatureStore(tmp_path / "analytic.db")
    try:
        last = _write(store, "ALT", prices)
        # lookback = 101 bars => exactly 100 returns, 50 of each sign.
        scores = LowVolSignal(lookback_days=len(prices)).score(store, last, ["ALT"])

        expected_sd = x * math.sqrt(n_returns / (n_returns - 1))
        expected_ann_vol = expected_sd * math.sqrt(252)

        recovered_ann_vol = (1.0 / scores["ALT"].value) - 1.0
        assert recovered_ann_vol == pytest.approx(expected_ann_vol, rel=1e-9)
    finally:
        store.close()


def test_future_bars_do_not_affect_the_score(tmp_path):
    """The central invariant, for this signal specifically.

    Calm for 252 days, then violent. Scored on the last calm day the signal
    must not see the violence; scored after it, it must.
    """
    calm = [100.0 * (1.001 ** i) for i in range(252)]
    wild = []
    px = calm[-1]
    for i in range(48):
        px *= 1.15 if i % 2 == 0 else 0.87
        wild.append(px)

    store = FeatureStore(tmp_path / "pit_lowvol.db")
    try:
        _write(store, "TURN", calm + wild)
        last_calm_day = d("2025-01-01") + dt.timedelta(days=len(calm) - 1)
        after_wild_day = d("2025-01-01") + dt.timedelta(days=len(calm) + len(wild) - 1)

        clean = LowVolSignal().score(store, last_calm_day, ["TURN"])["TURN"]
        leaked = LowVolSignal().score(store, after_wild_day, ["TURN"])["TURN"]

        # Constant growth => zero variance => 1 / (1 + 0) == 1.0
        assert clean.value == pytest.approx(1.0, abs=1e-6)
        # Once the violence is genuinely in the past it must show up, so the
        # assertion above cannot pass merely because the signal always says 1.0.
        assert leaked.value < 0.9
    finally:
        store.close()


def test_only_the_lookback_window_is_used(tmp_path):
    """Volatility must be measured over the configured window, not all history.

    Violent for 200 days, then calm for 252. With a 252-day lookback the old
    violence is outside the window and must not depress the score. Found by
    mutation testing: widening the store lookback passed every other test.
    """
    wild = []
    px = 100.0
    for i in range(200):
        px *= 1.15 if i % 2 == 0 else 0.87
        wild.append(px)
    calm = [px * (1.001 ** i) for i in range(252)]

    store = FeatureStore(tmp_path / "window.db")
    try:
        last = _write(store, "SETTLED", wild + calm)
        score = LowVolSignal(lookback_days=252).score(store, last, ["SETTLED"])["SETTLED"]
        assert score.value == pytest.approx(1.0, abs=1e-6)
    finally:
        store.close()


def test_lookback_below_two_is_rejected():
    with pytest.raises(ValueError, match="lookback_days"):
        LowVolSignal(lookback_days=1)


def test_non_positive_close_yields_no_opinion(tmp_path):
    """A zero or negative adjusted close would blow up log(); abstain instead."""
    prices = [100.0] * 300
    prices[150] = 0.0
    store = FeatureStore(tmp_path / "zero.db")
    try:
        last = _write(store, "ZERO", prices)
        assert LowVolSignal().score(store, last, ["ZERO"])["ZERO"].confidence == 0.0
    finally:
        store.close()