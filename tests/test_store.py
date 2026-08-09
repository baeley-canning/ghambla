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


def test_latest_bars_returns_one_bar_per_symbol(store):
    store.upsert_bars([bar("AAPL", "2026-01-05", 100.0), bar("AAPL", "2026-01-06", 101.0),
                       bar("MSFT", "2026-01-05", 200.0)])
    got = store.latest_bars_as_of(d("2026-01-06"), ["AAPL", "MSFT"])
    assert got["AAPL"].close == 101.0
    assert got["MSFT"].close == 200.0


def test_latest_bars_respects_the_as_of_date(store):
    store.upsert_bars([bar("AAPL", "2026-01-05", 100.0), bar("AAPL", "2026-01-06", 101.0)])
    got = store.latest_bars_as_of(d("2026-01-05"), ["AAPL"])
    assert got["AAPL"].close == 100.0


def test_latest_bars_carries_forward_a_symbol_that_did_not_trade(store):
    store.upsert_bars([bar("AAPL", "2026-01-05", 100.0), bar("MSFT", "2026-01-06", 200.0)])
    got = store.latest_bars_as_of(d("2026-01-06"), ["AAPL", "MSFT"])
    assert got["AAPL"].date == d("2026-01-05")


def test_latest_bars_omits_symbols_with_no_data(store):
    store.upsert_bars([bar("AAPL", "2026-01-05", 100.0)])
    assert "MSFT" not in store.latest_bars_as_of(d("2026-01-05"), ["AAPL", "MSFT"])


def test_latest_bars_of_nothing_is_empty(store):
    assert store.latest_bars_as_of(d("2026-01-05"), []) == {}


def test_latest_bars_agrees_with_the_per_symbol_read_path(store):
    """The fast path must not disagree with the audited one."""
    store.upsert_bars([bar("AAPL", f"2026-01-{day:02d}", 100.0 + day) for day in range(5, 15)]
                      + [bar("MSFT", f"2026-01-{day:02d}", 50.0 + day) for day in range(5, 12)])
    for day in range(5, 15):
        as_of = d(f"2026-01-{day:02d}")
        fast = store.latest_bars_as_of(as_of, ["AAPL", "MSFT"])
        slow = store.bars_as_of(as_of, ["AAPL", "MSFT"], lookback=1)
        assert {k: v for k, v in fast.items()} == {k: v[-1] for k, v in slow.items() if v}


def test_trading_dates_are_the_dates_we_actually_have_bars_for(store):
    store.upsert_bars([bar("AAPL", "2026-01-05", 100.0),
                       bar("MSFT", "2026-01-05", 200.0),
                       bar("AAPL", "2026-01-06", 101.0)])
    assert store.trading_dates(d("2026-01-01"), d("2026-01-31")) == [d("2026-01-05"), d("2026-01-06")]


# --- bars_as_of batching -----------------------------------------------


def test_bars_as_of_matches_a_naive_per_symbol_query(tmp_path):
    """Batching must not change a single returned row.

    bars_as_of is the point-in-time chokepoint every signal reads through, so
    a faster implementation has to be provably identical to the obvious one.
    """
    s = FeatureStore(tmp_path / "b.db")
    try:
        day = dt.date(2026, 1, 1)
        bars = []
        for i in range(40):
            for sym, base in (("AAA", 100.0), ("BBB", 50.0), ("CCC", 25.0)):
                px = base + i
                bars.append(Bar(sym, day, px, px, px, px, px, 1000 + i))
            day += dt.timedelta(days=1)
        s.upsert_bars(bars)

        def naive(as_of, symbols, lookback):
            out = {}
            for symbol in symbols:
                cur = s._conn.execute(
                    "SELECT * FROM bars WHERE symbol = ? AND knowable_at <= ?"
                    " ORDER BY date DESC LIMIT ?",
                    (symbol, as_of.isoformat(), lookback))
                found = [FeatureStore._to_bar(r) for r in cur.fetchall()]
                found.reverse()
                out[symbol] = found
            return out

        syms = ["AAA", "BBB", "CCC", "MISSING"]
        for as_of in (dt.date(2026, 1, 5), dt.date(2026, 1, 20), dt.date(2026, 3, 1)):
            for lookback in (1, 7, 100):
                assert s.bars_as_of(as_of, syms, lookback) == naive(as_of, syms, lookback), \
                    f"diverged at as_of={as_of} lookback={lookback}"
    finally:
        s.close()


def test_bars_as_of_includes_symbols_with_no_data_as_empty(tmp_path):
    """Callers do `history.get(sym, [])`; a missing key and an empty list must
    both work, but the existing contract returns the key."""
    s = FeatureStore(tmp_path / "b2.db")
    try:
        s.upsert_bars([Bar("AAA", dt.date(2026, 1, 1), 1, 1, 1, 1, 1, 1)])
        got = s.bars_as_of(dt.date(2026, 1, 5), ["AAA", "NOPE"], lookback=10)
        assert got["NOPE"] == []
        assert len(got["AAA"]) == 1
    finally:
        s.close()
