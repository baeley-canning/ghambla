import datetime as dt

import pytest

from ghambla.broker import Order, Position, SimulatedBroker
from ghambla.cycle import DailyCycle
from ghambla.journal import Journal
from ghambla.risk import RiskGate, RiskLimits
from ghambla.signals.base import Score
from ghambla.store.store import Bar, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


class Likes:
    """Stub signal that ranks the given symbols in order."""

    def __init__(self, order):
        self.order = order

    def score(self, store, as_of, universe):
        return {s: Score(value=float(len(self.order) - self.order.index(s))
                         if s in self.order else -1.0,
                         confidence=1.0, rationale="stub")
                for s in universe}


class Broken:
    def score(self, store, as_of, universe):
        raise RuntimeError("upstream API died")


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "c.db")
    day = d("2026-08-01")
    bars = []
    for i in range(6):
        for sym, px in (("AAA", 100.0), ("BBB", 50.0), ("CCC", 25.0), ("DDD", 10.0)):
            bars.append(Bar(sym, day, px, px, px, px, px, 1000))
        day += dt.timedelta(days=1)
    s.upsert_bars(bars)
    # Four names, so two sit above the median. Rank-centred scores make the
    # median exactly zero and the long-only constructor drops it, which with an
    # odd universe would leave only one eligible name.
    s.set_universe(d("2026-07-01"), ["AAA", "BBB", "CCC", "DDD"])
    yield s
    s.close()


def make(store, tmp_path, cash=10_000.0, signals=None, gate=None, top_n=2):
    broker = SimulatedBroker(cash=cash, spread_bps=0.0)
    broker.connect()
    journal = Journal(tmp_path / "j.jsonl")
    cycle = DailyCycle(store, signals or {"m": Likes(["AAA", "BBB"])},
                       broker, journal, mode="paper",
                       risk_gate=gate or RiskGate(RiskLimits(max_position_weight=1.0)),
                       top_n=top_n)
    return cycle, broker, journal


def test_first_cycle_buys_the_targets(store, tmp_path):
    cycle, broker, _ = make(store, tmp_path)
    r = cycle.run(d("2026-08-06"))
    assert not r.halted
    assert {o.symbol for o in r.orders} == {"AAA", "BBB"}
    assert set(broker.snapshot().positions) == {"AAA", "BBB"}


def test_fully_invested_targets_do_not_starve_the_last_order(store, tmp_path):
    """Sizing to exactly 100% of equity leaves nothing for commission, so the
    final buy is rejected for insufficient cash. The buffer prevents that."""
    cycle, broker, journal = make(store, tmp_path)
    r = cycle.run(d("2026-08-06"))
    assert len(r.fills) == len(r.orders), journal.last()["notes"]
    assert not any("rejected" in n for n in journal.last()["notes"])
    assert broker.snapshot().cash >= 0


def test_every_cycle_is_journalled(store, tmp_path):
    cycle, _, journal = make(store, tmp_path)
    cycle.run(d("2026-08-06"))
    rec = journal.last()
    assert rec["mode"] == "paper"
    assert rec["universe_size"] == 4
    assert rec["allocator"] == "rank_average"
    assert "AAA" in rec["targets"]


def test_second_cycle_reconciles_against_the_first(store, tmp_path):
    cycle, _, journal = make(store, tmp_path)
    cycle.run(d("2026-08-06"))
    r2 = cycle.run(d("2026-08-06"))
    assert not r2.halted
    assert journal.count() == 2


def test_drift_injected_behind_our_back_halts_trading(store, tmp_path):
    """The failure mode reconciliation exists to catch."""
    cycle, broker, _ = make(store, tmp_path)
    cycle.run(d("2026-08-06"))
    broker._positions["ZZZ"] = Position("ZZZ", 99.0, 1.0)  # unexplained holding
    r = cycle.run(d("2026-08-06"))
    assert r.halted
    assert any("unexpected" in reason for reason in r.reasons)


def test_a_halt_places_no_orders(store, tmp_path):
    cycle, broker, _ = make(store, tmp_path)
    cycle.run(d("2026-08-06"))
    before = dict(broker.snapshot().positions)
    broker._positions["ZZZ"] = Position("ZZZ", 99.0, 1.0)
    cycle.run(d("2026-08-06"))
    after = broker.snapshot().positions
    assert {k: v.shares for k, v in after.items() if k != "ZZZ"} == \
           {k: v.shares for k, v in before.items()}


def test_manual_halt_blocks_and_is_recorded(store, tmp_path):
    cycle, _, journal = make(store, tmp_path)
    r = cycle.run(d("2026-08-06"), halt=True)
    assert r.halted
    assert r.orders == []
    assert any("manual halt" in v for v in journal.last()["risk_vetoes"])


def test_stale_data_halts(store, tmp_path):
    cycle, _, _ = make(store, tmp_path)
    r = cycle.run(d("2026-09-30"))  # far beyond the last bar
    assert r.halted
    assert any("days old" in reason for reason in r.reasons)


def test_a_failing_signal_does_not_kill_the_cycle(store, tmp_path):
    cycle, _, journal = make(store, tmp_path,
                             signals={"m": Likes(["AAA", "BBB"]), "broken": Broken()})
    r = cycle.run(d("2026-08-06"))
    assert not r.halted
    assert any("broken" in n for n in journal.last()["notes"])


def test_a_halted_cycle_is_still_journalled(store, tmp_path):
    """A cycle that halted without recording why looks like one that never ran."""
    cycle, _, journal = make(store, tmp_path)
    cycle.run(d("2026-08-06"), halt=True)
    assert journal.count() == 1
    assert journal.last()["risk_vetoes"]


def test_risk_cap_shrinks_the_position(store, tmp_path):
    gate = RiskGate(RiskLimits(max_position_weight=0.10))
    cycle, broker, journal = make(store, tmp_path, gate=gate)
    cycle.run(d("2026-08-06"))
    assert all(w <= 0.10 + 1e-9 for w in journal.last()["targets"].values())


def test_sells_are_ordered_before_buys(store, tmp_path):
    """Proceeds from sells must be available to fund the buys."""
    cycle, broker, _ = make(store, tmp_path, signals={"m": Likes(["AAA", "BBB"])})
    cycle.run(d("2026-08-06"))
    cycle.signals = {"m": Likes(["CCC"])}
    r = cycle.run(d("2026-08-06"))
    sides = [o.side for o in r.orders]
    assert sides == sorted(sides, key=lambda s: s != "SELL")


def test_rationale_is_preserved_for_later_diagnosis(store, tmp_path):
    cycle, _, journal = make(store, tmp_path)
    cycle.run(d("2026-08-06"))
    scores = journal.last()["signal_scores"]["m"]
    assert scores["AAA"]["rationale"] == "stub"


# --- the backtest and the live cycle must agree ------------------------


class AllNegative:
    """Every name is a sell. Raw scores mean 'hold nothing'."""

    def score(self, store, as_of, universe):
        return {s: Score(value=-1.0, confidence=1.0, rationale="stub") for s in universe}


def test_a_lone_signal_can_still_go_to_cash(store, tmp_path):
    """Gate 0 must validate what the live cycle actually runs.

    `run_backtest` scores a single signal raw, so an all-negative signal buys
    nothing and sits in cash — that is how momentum survives a drawdown. The
    cycle used to rank-centre even a lone signal, which makes half the universe
    positive by construction and buys regardless. Same signal, same day, two
    different portfolios, and only one of them was ever measured.
    """
    cycle, broker, _ = make(store, tmp_path, signals={"neg": AllNegative()})
    r = cycle.run(d("2026-08-06"))
    assert r.targets == {}
    assert r.orders == []
    assert broker.snapshot().positions == {}


def test_lone_signal_matches_the_backtest_combination(store, tmp_path):
    """Both paths must route through one combination rule, not two."""
    from ghambla.allocator import RankAllocator
    from ghambla.backtest import score_universe

    sig = Likes(["AAA", "BBB"])
    universe = store.universe_as_of(d("2026-08-06"))
    expected = score_universe(store, d("2026-08-06"), universe,
                              {"m": sig}, RankAllocator())
    cycle, _, _ = make(store, tmp_path, signals={"m": sig})
    r = cycle.run(d("2026-08-06"))
    top = sorted(expected, key=lambda s: (-expected[s].value, s))[:2]
    assert set(r.targets) == set(top)


def test_two_signals_are_still_rank_combined(store, tmp_path):
    """Ranking is what makes incomparable signals comparable; keep it for >1."""
    cycle, _, journal = make(store, tmp_path,
                             signals={"a": Likes(["AAA", "BBB"]),
                                      "b": Likes(["BBB", "AAA"])})
    cycle.run(d("2026-08-06"))
    rationales = " ".join(t for t in journal.last()["targets"])
    assert set(journal.last()["targets"]) == {"AAA", "BBB"}, rationales


def test_when_one_of_two_signals_dies_the_survivor_is_not_centred(store, tmp_path):
    """A broken signal must not silently flip the survivor into rank space."""
    cycle, broker, _ = make(store, tmp_path,
                            signals={"neg": AllNegative(), "boom": Broken()})
    r = cycle.run(d("2026-08-06"))
    assert r.targets == {}
    assert broker.snapshot().positions == {}


def test_cycle_supports_the_same_weighting_schemes_as_the_backtest(store, tmp_path):
    """Whatever Gate 0 measured is what the cycle must run.

    The backtest gained inverse-vol weighting; if the cycle could not also run
    it, adopting it would recreate exactly the validate-one-thing-run-another
    split that `combine_scores` was written to close.
    """
    broker = SimulatedBroker(cash=10_000.0, spread_bps=0.0)
    broker.connect()
    cycle = DailyCycle(store, {"m": Likes(["AAA", "BBB"])}, broker,
                       Journal(tmp_path / "w.jsonl"), mode="paper",
                       risk_gate=RiskGate(RiskLimits(max_position_weight=1.0)),
                       top_n=2, weighting="invvol")
    r = cycle.run(d("2026-08-06"))
    assert set(r.targets) == {"AAA", "BBB"}
    assert sum(r.targets.values()) == pytest.approx(1.0)


def test_cycle_rejects_an_unknown_weighting(store, tmp_path):
    with pytest.raises(ValueError, match="weighting"):
        DailyCycle(store, {"m": Likes(["AAA"])}, SimulatedBroker(cash=1.0),
                   Journal(tmp_path / "w2.jsonl"), mode="paper", weighting="magic")
