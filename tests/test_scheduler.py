"""Daily scheduler tests."""
import datetime as dt

import pytest

from ghambla.broker import SimulatedBroker
from ghambla.journal import Journal
from ghambla.scheduler import DailyScheduler
from ghambla.signals.base import Score
from ghambla.store.store import Bar, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _seed(db_path, n_days=10):
    s = FeatureStore(db_path)
    day = d("2026-08-01")
    bars = []
    for i in range(n_days):
        for sym, px in (("AAA", 100.0), ("BBB", 50.0)):
            bars.append(Bar(sym, day, px, px, px, px, px, 1000))
        day += dt.timedelta(days=1)
    s.upsert_bars(bars)
    s.set_universe(d("2026-07-01"), ["AAA", "BBB"])
    return s


class Likes:
    name = "likes"

    def score(self, store, as_of, universe):
        return {sym: Score(value=1.0 if sym == "AAA" else 0.0,
                           confidence=1.0, rationale="stub") for sym in universe}


def make(store, tmp_path):
    broker = SimulatedBroker(cash=10_000.0, spread_bps=0.0)
    broker.connect()
    journal = Journal(tmp_path / "j.jsonl")
    scheduler = DailyScheduler(store, {"m": Likes()}, broker, journal,
                               mode="simulated", top_n=1)
    return scheduler, broker, journal


def test_run_once_executes_a_cycle(tmp_path):
    store = _seed(tmp_path / "s.db")
    try:
        scheduler, broker, journal = make(store, tmp_path)
        result = scheduler.run_once(d("2026-08-10"))
        assert result.ran
        assert not result.halted
        assert journal.count() == 1
        assert set(broker.snapshot().positions) == {"AAA"}
    finally:
        store.close()


def test_run_once_is_idempotent_per_date(tmp_path):
    store = _seed(tmp_path / "s.db")
    try:
        scheduler, _, journal = make(store, tmp_path)
        scheduler.run_once(d("2026-08-10"))
        result = scheduler.run_once(d("2026-08-10"))
        assert not result.ran
        assert "already ran" in result.notes[0]
        assert journal.count() == 1
    finally:
        store.close()


def test_run_once_defaults_to_latest_trading_day(tmp_path):
    # Fresh store whose last bar (2026-01-10) is before "today", so the
    # default pick is deterministic.
    store = FeatureStore(tmp_path / "default.db")
    day = d("2026-01-01")
    bars = []
    for i in range(10):
        for sym, px in (("AAA", 100.0), ("BBB", 50.0)):
            bars.append(Bar(sym, day, px, px, px, px, px, 1000))
        day += dt.timedelta(days=1)
    store.upsert_bars(bars)
    store.set_universe(d("2025-12-01"), ["AAA", "BBB"])
    try:
        scheduler, _, journal = make(store, tmp_path)
        result = scheduler.run_once()
        assert result.ran
        assert result.as_of == d("2026-01-10")
    finally:
        store.close()


def test_run_once_catches_cycle_failures(tmp_path):
    store = _seed(tmp_path / "s.db")
    try:
        journal = Journal(tmp_path / "j.jsonl")

        class BrokenBroker:
            """A broker whose snapshot raises — the cycle cannot even start."""

            name = "broken"

            def connect(self):
                pass

            def disconnect(self):
                pass

            def snapshot(self):
                raise RuntimeError("broker down")

            def place(self, order, reference_price):
                raise AssertionError("should never place")

        scheduler = DailyScheduler(store, {"m": Likes()}, BrokenBroker(), journal,
                                   mode="simulated", top_n=1)
        result = scheduler.run_once(d("2026-08-10"))
        assert result.halted
        assert "broker down" in result.error
    finally:
        store.close()
