"""The central invariant: no read may return a fact from the future.

`test_planted_lookahead_bug_is_caught` is required by Gate 0 of the design
doc. It proves the suite can actually detect lookahead, rather than merely
asserting that correct code is correct.
"""
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
    s = FeatureStore(tmp_path / "pit.db")
    s.upsert_bars([bar("AAPL", f"2026-01-{day:02d}", 100.0 + day) for day in range(5, 26)])
    yield s
    s.close()


def test_future_bars_are_never_returned(store):
    got = store.bars_as_of(d("2026-01-15"), ["AAPL"], lookback=100)
    assert max(b.date for b in got["AAPL"]) == d("2026-01-15")


def test_no_returned_bar_postdates_the_as_of_for_any_as_of(store):
    # Property test across every as-of date in range.
    for day in range(5, 26):
        as_of = d(f"2026-01-{day:02d}")
        got = store.bars_as_of(as_of, ["AAPL"], lookback=100)
        assert all(b.date <= as_of for b in got["AAPL"]), f"leak at {as_of}"


def test_data_ingested_later_does_not_change_an_earlier_as_of_view(store):
    before = store.bars_as_of(d("2026-01-15"), ["AAPL"], lookback=100)
    store.upsert_bars([bar("AAPL", "2026-02-01", 999.0)])
    after = store.bars_as_of(d("2026-01-15"), ["AAPL"], lookback=100)
    assert before == after


def test_planted_lookahead_bug_is_caught(store, monkeypatch):
    """Replace the read path with one that ignores `as_of`, and assert our
    invariant check notices. If this ever fails, the detection method itself
    is broken and every other point-in-time test is worthless."""

    def leaky_bars_as_of(self, as_of, symbols, lookback):
        out = {}
        for symbol in symbols:
            cur = self._conn.execute(
                "SELECT * FROM bars WHERE symbol = ? ORDER BY date DESC LIMIT ?",
                (symbol, lookback),
            )
            found = [FeatureStore._to_bar(r) for r in cur.fetchall()]
            found.reverse()
            out[symbol] = found
        return out

    monkeypatch.setattr(FeatureStore, "bars_as_of", leaky_bars_as_of)

    as_of = d("2026-01-15")
    got = store.bars_as_of(as_of, ["AAPL"], lookback=100)
    leaked = [b.date for b in got["AAPL"] if b.date > as_of]
    assert leaked, "planted bug did not leak — the detection method is wrong"
