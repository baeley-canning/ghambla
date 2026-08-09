"""The backtest and the live cycle must not silently diverge.

The design doc's rule: one decision path, three execution backends; any logic
in only one path is a bug waiting to happen. Three such bugs have shipped —
the scorer, the risk gate, and the cash buffer — and every one was found by
hand, after the fact. This test finds the fourth.
"""
import datetime as dt
import inspect

import pytest

from ghambla import backtest, cycle


def test_every_decision_knob_exists_on_both_paths():
    """A parameter that shapes decisions must be honoured by both engines."""
    bt = set(inspect.signature(backtest.run_backtest).parameters)
    cy = set(inspect.signature(cycle.DailyCycle.__init__).parameters)
    shared = {"top_n", "weighting", "regime_filter", "risk_gate", "cash_buffer"}
    assert not shared - bt, f"backtest missing decision knobs: {sorted(shared - bt)}"
    assert not shared - cy, f"cycle missing decision knobs: {sorted(shared - cy)}"


def test_same_signal_and_day_gives_the_same_targets(tmp_path):
    """The strongest form: run both engines on one day and compare targets."""
    from ghambla.broker import SimulatedBroker
    from ghambla.journal import Journal
    from ghambla.risk import RiskGate, RiskLimits
    from ghambla.signals.base import Score
    from ghambla.store.store import Bar, FeatureStore

    class Likes:
        name = "likes"

        def score(self, store, as_of, universe):
            order = ["AAA", "BBB", "CCC"]
            return {s: Score(value=float(len(order) - order.index(s))
                             if s in order else -1.0,
                             confidence=1.0, rationale="stub")
                    for s in universe}

    store = FeatureStore(tmp_path / "parity.db")
    day = dt.date(2026, 1, 1)
    bars = []
    for _ in range(40):
        for sym, px in (("AAA", 100.0), ("BBB", 50.0), ("CCC", 25.0)):
            bars.append(Bar(sym, day, px, px, px, px, px, 10_000))
        day += dt.timedelta(days=1)
    store.upsert_bars(bars)
    store.set_universe(dt.date(2025, 12, 1), ["AAA", "BBB", "CCC"])
    try:
        as_of = store.trading_dates(dt.date(2026, 1, 1), dt.date(2026, 2, 9))[-1]
        broker = SimulatedBroker(cash=10_000.0, spread_bps=0.0)
        broker.connect()
        c = cycle.DailyCycle(store, {"m": Likes()}, broker,
                             Journal(tmp_path / "p.jsonl"), mode="paper",
                             risk_gate=RiskGate(RiskLimits(max_position_weight=1.0)),
                             top_n=2)
        cycle_targets = c.run(as_of).targets

        scores = backtest.score_universe(store, as_of, ["AAA", "BBB", "CCC"],
                                         {"m": Likes()}, backtest.RankAllocator())
        bt_targets = {t.symbol: t.weight
                      for t in backtest.weigh(scores, 2, "equal", store, as_of, 252)}
        assert set(cycle_targets) == set(bt_targets)
    finally:
        store.close()
