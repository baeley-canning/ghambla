"""The live-quote boundary.

A quote may set the price an order is *sent* at. It must never reach a signal,
never move the equity mark, and never stop the cycle when the feed dies. A
quote has no `knowable_at` and cannot be replayed, so a signal that saw one
would make every backtest number unreproducible.
"""
import datetime as dt

import pytest

from ghambla.broker import SimulatedBroker
from ghambla.cycle import DailyCycle
from ghambla.journal import Journal
from ghambla.quotes import Quote
from ghambla.risk import RiskGate, RiskLimits
from ghambla.signals.base import Score
from ghambla.store.store import Bar, FeatureStore

STORED_CLOSE = 100.0
LIVE_MID = 250.0


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


class Likes:
    def __init__(self, order):
        self.order = order
        self.seen_prices = []

    def score(self, store, as_of, universe):
        # Record what the signal could see, to prove no quote reached it.
        bars = store.latest_bars_as_of(as_of, universe)
        self.seen_prices.extend(b.close for b in bars.values())
        return {s: Score(value=1.0 if s in self.order else -1.0,
                         confidence=1.0, rationale="stub") for s in universe}


class StubQuotes:
    name = "stub"

    def __init__(self, mapping=None, boom=False):
        self.mapping = mapping or {}
        self.boom = boom
        self.asked = []

    def quotes(self, symbols):
        if self.boom:
            raise RuntimeError("feed down")
        self.asked.append(sorted(symbols))
        return {s: self.mapping[s] for s in symbols if s in self.mapping}


def quote(symbol, mid):
    return Quote(symbol=symbol, last=mid, bid=None, ask=None,
                 at=dt.datetime.now(dt.UTC), source="stub")


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "q.db")
    day = d("2026-08-01")
    bars = []
    for _ in range(6):
        for sym in ("AAA", "BBB", "CCC", "DDD"):
            bars.append(Bar(sym, day, STORED_CLOSE, STORED_CLOSE, STORED_CLOSE,
                            STORED_CLOSE, STORED_CLOSE, 1000))
        day += dt.timedelta(days=1)
    s.upsert_bars(bars)
    s.set_universe(d("2026-07-01"), ["AAA", "BBB", "CCC", "DDD"])
    yield s
    s.close()


def make(store, tmp_path, quote_source=None, signal=None):
    broker = SimulatedBroker(cash=10_000.0, spread_bps=0.0)
    broker.connect()
    journal = Journal(tmp_path / "j.jsonl")
    cycle = DailyCycle(store, {"m": signal or Likes(["AAA", "BBB"])},
                       broker, journal, mode="paper",
                       risk_gate=RiskGate(RiskLimits(max_position_weight=1.0)),
                       top_n=2, quote_source=quote_source)
    return cycle, broker, journal


def test_without_a_quote_source_nothing_changes(store, tmp_path):
    cycle, _, _ = make(store, tmp_path)
    r = cycle.run(d("2026-08-06"))
    assert r.fills
    assert all(f.price == pytest.approx(STORED_CLOSE) for f in r.fills)


def test_orders_fill_at_the_live_mid_not_the_stored_close(store, tmp_path):
    src = StubQuotes({s: quote(s, LIVE_MID) for s in ("AAA", "BBB")})
    cycle, _, _ = make(store, tmp_path, quote_source=src)
    r = cycle.run(d("2026-08-06"))
    assert r.fills
    assert all(f.price == pytest.approx(LIVE_MID) for f in r.fills)


def test_the_signal_never_sees_a_live_quote(store, tmp_path):
    """The whole point. Signals read the point-in-time store and nothing else."""
    signal = Likes(["AAA", "BBB"])
    src = StubQuotes({s: quote(s, LIVE_MID) for s in ("AAA", "BBB")})
    cycle, _, _ = make(store, tmp_path, quote_source=src, signal=signal)
    cycle.run(d("2026-08-06"))
    assert signal.seen_prices, "signal was never scored"
    assert all(p == pytest.approx(STORED_CLOSE) for p in signal.seen_prices)
    assert LIVE_MID not in signal.seen_prices


def test_equity_is_marked_on_stored_closes_not_quotes(store, tmp_path):
    """Marking on a live quote would make the journal's equity unreplayable."""
    src = StubQuotes({s: quote(s, LIVE_MID) for s in ("AAA", "BBB")})
    cycle, _, journal = make(store, tmp_path, quote_source=src)
    cycle.run(d("2026-08-06"))
    # Bought at 250 but marked at 100, so equity must fall well below the
    # starting cash rather than being flattered by the quote.
    assert journal.last()["equity"] < 10_000.0


def test_a_dead_quote_feed_does_not_stop_trading(store, tmp_path):
    cycle, _, journal = make(store, tmp_path, quote_source=StubQuotes(boom=True))
    r = cycle.run(d("2026-08-06"))
    assert not r.halted
    assert r.fills
    assert all(f.price == pytest.approx(STORED_CLOSE) for f in r.fills)
    assert any("quote source failed" in n for n in journal.last()["notes"])


def test_a_missing_quote_falls_back_to_the_stored_close(store, tmp_path):
    src = StubQuotes({"AAA": quote("AAA", LIVE_MID)})  # BBB absent
    cycle, _, journal = make(store, tmp_path, quote_source=src)
    r = cycle.run(d("2026-08-06"))
    by_symbol = {f.symbol: f.price for f in r.fills}
    assert by_symbol["AAA"] == pytest.approx(LIVE_MID)
    assert by_symbol["BBB"] == pytest.approx(STORED_CLOSE)
    assert any("no live quote for BBB" in n for n in journal.last()["notes"])


def test_quotes_are_only_requested_for_symbols_being_ordered(store, tmp_path):
    """No point paying for, or waiting on, quotes we will not trade."""
    src = StubQuotes({s: quote(s, LIVE_MID) for s in ("AAA", "BBB")})
    cycle, _, _ = make(store, tmp_path, quote_source=src)
    cycle.run(d("2026-08-06"))
    assert src.asked
    assert set(src.asked[0]) <= {"AAA", "BBB"}
