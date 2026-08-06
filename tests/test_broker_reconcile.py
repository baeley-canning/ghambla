import pytest

from ghambla.allocator import RankAllocator
from ghambla.broker import AccountSnapshot, Order, OrderError, Position, SimulatedBroker
from ghambla.reconcile import reconcile
from ghambla.signals.base import Score


def s(v, conf=1.0):
    return Score(value=v, confidence=conf, rationale="t")


# --- allocator ---

def test_rank_average_centres_on_zero():
    a = RankAllocator()
    out = a.combine({"m": {"A": s(0.9), "B": s(0.5), "C": s(0.1)}})
    assert out["A"].value == pytest.approx(0.5)
    assert out["B"].value == pytest.approx(0.0)
    assert out["C"].value == pytest.approx(-0.5)


def test_disagreeing_signals_average_out():
    a = RankAllocator()
    out = a.combine({
        "m": {"A": s(1.0), "B": s(0.0)},
        "f": {"A": s(0.0), "B": s(1.0)},
    })
    assert out["A"].value == pytest.approx(0.0)
    assert out["B"].value == pytest.approx(0.0)


def test_scale_differences_between_signals_do_not_matter():
    """Rank averaging means a signal emitting huge numbers cannot dominate."""
    a = RankAllocator()
    small = a.combine({"m": {"A": s(0.02), "B": s(0.01)}, "f": {"A": s(1.0), "B": s(2.0)}})
    huge = a.combine({"m": {"A": s(2e9), "B": s(1e9)}, "f": {"A": s(1.0), "B": s(2.0)}})
    assert small["A"].value == pytest.approx(huge["A"].value)


def test_abstention_is_not_a_neutral_vote():
    a = RankAllocator()
    out = a.combine({
        "m": {"A": s(1.0), "B": s(0.0)},
        "f": {"A": s(0.0, conf=0.0), "B": s(0.0, conf=0.0)},
    })
    # only momentum voted, so its ranking stands unchanged
    assert out["A"].value == pytest.approx(0.5)


def test_symbol_no_signal_has_an_opinion_on_gets_no_opinion():
    out = RankAllocator().combine({"m": {"A": s(1.0, conf=0.0)}})
    assert out["A"].confidence == 0.0


def test_weights_shift_the_balance():
    a = RankAllocator(weights={"m": 3.0, "f": 1.0})
    out = a.combine({
        "m": {"A": s(1.0), "B": s(0.0)},
        "f": {"A": s(0.0), "B": s(1.0)},
    })
    assert out["A"].value > out["B"].value


def test_no_signals_yields_nothing():
    assert RankAllocator().combine({}) == {}


# --- simulated broker ---

def test_buy_then_snapshot():
    b = SimulatedBroker(cash=10_000.0, spread_bps=0.0)
    b.connect()
    fill = b.place(Order("AAA", "BUY", 10), reference_price=100.0)
    snap = b.snapshot()
    assert fill.price == pytest.approx(100.0)
    assert snap.positions["AAA"].shares == pytest.approx(10)
    assert snap.cash == pytest.approx(10_000.0 - 1000.0 - fill.commission)


def test_sell_closes_the_position():
    b = SimulatedBroker(cash=10_000.0, spread_bps=0.0)
    b.connect()
    b.place(Order("AAA", "BUY", 10), 100.0)
    b.place(Order("AAA", "SELL", 10), 110.0)
    assert b.snapshot().positions == {}


def test_cannot_trade_while_disconnected():
    b = SimulatedBroker()
    with pytest.raises(OrderError, match="not connected"):
        b.place(Order("AAA", "BUY", 1), 100.0)


def test_cannot_spend_cash_it_does_not_have():
    b = SimulatedBroker(cash=100.0)
    b.connect()
    with pytest.raises(OrderError, match="insufficient cash"):
        b.place(Order("AAA", "BUY", 10), 100.0)


def test_cannot_sell_what_it_does_not_hold():
    b = SimulatedBroker(cash=10_000.0)
    b.connect()
    with pytest.raises(OrderError, match="cannot sell"):
        b.place(Order("AAA", "SELL", 5), 100.0)


def test_buy_pays_above_and_sell_receives_below_the_reference():
    b = SimulatedBroker(cash=10_000.0, spread_bps=100.0)
    b.connect()
    bought = b.place(Order("AAA", "BUY", 10), 100.0)
    sold = b.place(Order("AAA", "SELL", 10), 100.0)
    assert bought.price > 100.0 > sold.price


# --- reconciliation ---

def snap(cash, **positions):
    return AccountSnapshot(cash=cash,
                           positions={s: Position(s, q, 100.0) for s, q in positions.items()})


def test_matching_state_reconciles():
    assert reconcile({"AAA": 10.0}, 500.0, snap(500.0, AAA=10.0)).ok


def test_share_drift_is_a_break():
    r = reconcile({"AAA": 10.0}, 500.0, snap(500.0, AAA=12.0))
    assert not r.ok
    assert "shares mismatch in AAA" in r.describe()[0]


def test_a_position_the_broker_does_not_have():
    r = reconcile({"AAA": 10.0}, 500.0, snap(500.0))
    assert r.breaks[0].kind == "missing"


def test_a_position_we_did_not_know_about():
    r = reconcile({}, 500.0, snap(500.0, ZZZ=3.0))
    assert r.breaks[0].kind == "unexpected"


def test_cash_drift_is_a_break():
    r = reconcile({}, 500.0, snap(487.31))
    assert r.breaks[0].kind == "cash"


def test_floating_point_noise_is_tolerated():
    assert reconcile({"AAA": 10.0}, 500.0, snap(500.000001, AAA=10.00000001)).ok


def test_one_missed_fill_trips_the_tolerance():
    """Tolerances must be tight enough to catch a real error, not just noise."""
    assert not reconcile({"AAA": 10.0}, 500.0, snap(500.0, AAA=10.01)).ok
