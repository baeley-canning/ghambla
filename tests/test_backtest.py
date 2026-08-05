import datetime as dt

import pytest

from ghambla.backtest import run_backtest
from ghambla.signals.base import Score
from ghambla.store.store import Bar, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


class AlwaysBuy:
    """Signal stub that always favours one symbol."""
    name = "always_buy"

    def __init__(self, symbol="AAA"):
        self.symbol = symbol

    def score(self, store, as_of, universe):
        return {s: Score(value=1.0 if s == self.symbol else -1.0,
                         confidence=1.0, rationale="stub") for s in universe}


class NeverBuy:
    name = "never_buy"

    def score(self, store, as_of, universe):
        return {s: Score(value=-1.0, confidence=1.0, rationale="stub") for s in universe}


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "bt.db")
    day = d("2026-01-01")
    bars = []
    for i in range(60):
        # open deliberately differs from close so a close-filling bug is visible
        bars.append(Bar(symbol="AAA", date=day, open=100.0 + i, high=110.0 + i,
                        low=90.0 + i, close=105.0 + i, adj_close=105.0 + i, volume=10_000))
        day += dt.timedelta(days=1)
    s.upsert_bars(bars)
    s.set_universe(d("2025-12-01"), ["AAA"])
    yield s
    s.close()


def test_no_trades_when_signal_never_buys(store):
    r = run_backtest(store, NeverBuy(), d("2026-01-01"), d("2026-02-28"), initial_cash=10_000.0)
    assert r.trades == []
    assert r.equity[-1] == pytest.approx(10_000.0)


def test_fills_at_next_bar_open_not_signal_bar_close(store):
    """The rule the whole engine exists to enforce."""
    dates = store.trading_dates(d("2026-01-01"), d("2026-02-28"))
    r = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0, rebalance_every=1000, spread_bps=0.0)
    assert r.trades, "expected at least one trade"
    first = r.trades[0]

    # Decision is taken on dates[0]'s close, so the fill must land on dates[1].
    assert first.date == dates[1]

    decision_bar = store.bars_as_of(dates[0], ["AAA"], lookback=1)["AAA"][-1]
    fill_bar = store.bars_as_of(dates[1], ["AAA"], lookback=1)["AAA"][-1]

    assert first.price == pytest.approx(fill_bar.open)
    assert first.price != pytest.approx(decision_bar.close)


def test_commission_is_charged_on_every_trade(store):
    r = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"), initial_cash=10_000.0)
    assert r.trades
    assert all(t.commission > 0 for t in r.trades)


def test_equity_curve_has_one_point_per_trading_day(store):
    r = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"), initial_cash=10_000.0)
    expected = store.trading_dates(d("2026-01-01"), d("2026-02-28"))
    assert r.dates == expected
    assert len(r.equity) == len(expected)


def test_equity_never_goes_negative(store):
    r = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0, rebalance_every=1)
    assert all(e >= 0 for e in r.equity)


def test_spread_makes_buys_more_expensive_than_the_open(store):
    r = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0, rebalance_every=1000, spread_bps=100.0)
    first = r.trades[0]
    fill_bar = store.bars_as_of(first.date, ["AAA"], lookback=1)["AAA"][-1]
    assert first.price > fill_bar.open


def test_empty_date_range_yields_empty_result(store):
    r = run_backtest(store, AlwaysBuy(), d("2020-01-01"), d("2020-12-31"))
    assert r.dates == []
    assert r.equity == []
    assert r.trades == []


def test_position_is_sold_when_signal_stops_liking_it(store):
    """Buy on the first decision, then flip the signal and confirm it exits."""
    dates = store.trading_dates(d("2026-01-01"), d("2026-02-28"))

    class FlipFlop:
        name = "flipflop"

        def score(self, store, as_of, universe):
            liked = as_of < dates[10]
            return {s: Score(value=1.0 if liked else -1.0, confidence=1.0,
                             rationale="stub") for s in universe}

    r = run_backtest(store, FlipFlop(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0, rebalance_every=5)
    sides = [t.side for t in r.trades]
    assert "BUY" in sides
    assert "SELL" in sides
