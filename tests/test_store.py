import datetime as dt

import pytest

from ghambla.store.store import Bar, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def bar(sym: str, day: str, close: float) -> Bar:
    return Bar(symbol=sym, date=d(day), open=close, high=close, low=close,
               close=close, adj_close=close, volume=1000)


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "test.db")
    yield s
    s.close()


def test_upsert_then_read_back(store):
    store.upsert_bars([bar("AAPL", "2026-01-05", 100.0)])
    got = store.bars_as_of(d("2026-01-05"), ["AAPL"], lookback=10)
    assert len(got["AAPL"]) == 1
    assert got["AAPL"][0].close == 100.0


def test_upsert_is_idempotent(store):
    store.upsert_bars([bar("AAPL", "2026-01-05", 100.0)])
    store.upsert_bars([bar("AAPL", "2026-01-05", 101.0)])
    got = store.bars_as_of(d("2026-01-05"), ["AAPL"], lookback=10)
    assert len(got["AAPL"]) == 1
    assert got["AAPL"][0].close == 101.0


def test_bars_are_returned_oldest_first(store):
    store.upsert_bars([bar("AAPL", "2026-01-07", 102.0),
                       bar("AAPL", "2026-01-05", 100.0),
                       bar("AAPL", "2026-01-06", 101.0)])
    got = store.bars_as_of(d("2026-01-07"), ["AAPL"], lookback=10)
    assert [b.date for b in got["AAPL"]] == [d("2026-01-05"), d("2026-01-06"), d("2026-01-07")]


def test_lookback_returns_the_most_recent_n_bars(store):
    store.upsert_bars([bar("AAPL", f"2026-01-{day:02d}", 100.0 + day) for day in range(5, 15)])
    got = store.bars_as_of(d("2026-01-14"), ["AAPL"], lookback=3)
    assert [b.date for b in got["AAPL"]] == [d("2026-01-12"), d("2026-01-13"), d("2026-01-14")]


def test_missing_symbol_yields_empty_list_not_keyerror(store):
    store.upsert_bars([bar("AAPL", "2026-01-05", 100.0)])
    got = store.bars_as_of(d("2026-01-05"), ["AAPL", "MSFT"], lookback=10)
    assert got["MSFT"] == []


def test_universe_membership_is_dated(store):
    store.set_universe(d("2026-01-01"), ["AAPL", "MSFT"])
    store.set_universe(d("2026-06-01"), ["AAPL", "MSFT", "NVDA"])
    assert store.universe_as_of(d("2026-03-01")) == ["AAPL", "MSFT"]
    assert store.universe_as_of(d("2026-07-01")) == ["AAPL", "MSFT", "NVDA"]


def test_universe_before_any_snapshot_is_empty(store):
    store.set_universe(d("2026-01-01"), ["AAPL"])
    assert store.universe_as_of(d("2025-12-31")) == []


def test_trading_dates_are_the_dates_we_actually_have_bars_for(store):
    store.upsert_bars([bar("AAPL", "2026-01-05", 100.0),
                       bar("MSFT", "2026-01-05", 200.0),
                       bar("AAPL", "2026-01-06", 101.0)])
    assert store.trading_dates(d("2026-01-01"), d("2026-01-31")) == [d("2026-01-05"), d("2026-01-06")]
