import datetime as dt

import pytest

from ghambla.risk import RiskGate, RiskLimits, RiskState


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def state(**kw):
    base = dict(equity=10_000.0, peak_equity=10_000.0, previous_equity=10_000.0,
                data_as_of=d("2026-08-05"), today=d("2026-08-05"))
    base.update(kw)
    return RiskState(**base)


# Five equal names at 20% each: exactly at the position cap, fully invested,
# so a correct gate leaves this untouched.
EVEN = {"A": 0.20, "B": 0.20, "C": 0.20, "D": 0.20, "E": 0.20}


# --- the invariant: never increases exposure ---

def test_gate_never_increases_any_weight():
    gate = RiskGate()
    out = gate.evaluate(EVEN, state())
    for sym, weight in out.targets.items():
        assert weight <= EVEN[sym] + 1e-12


def test_gate_never_invents_a_position():
    out = RiskGate().evaluate(EVEN, state())
    assert set(out.targets) <= set(EVEN)


def test_untouched_targets_pass_through():
    out = RiskGate().evaluate(EVEN, state())
    assert out.allowed
    assert out.targets == EVEN
    assert out.vetoes == []


# --- hard stops ---

def test_manual_halt_blocks_everything():
    out = RiskGate().evaluate(EVEN, state(halted=True, halt_reason="kill switch"))
    assert not out.allowed
    assert out.targets == {}
    assert "kill switch" in out.vetoes[0]


def test_failed_reconciliation_blocks_trading():
    out = RiskGate().evaluate(EVEN, state(reconciled=False))
    assert not out.allowed
    assert "reconcile" in out.vetoes[0]


def test_stale_data_blocks_trading():
    out = RiskGate().evaluate(EVEN, state(data_as_of=d("2026-07-20")))
    assert not out.allowed
    assert "days old" in out.vetoes[0]


def test_fresh_data_within_tolerance_is_fine():
    # a long weekend is not staleness
    out = RiskGate().evaluate(EVEN, state(data_as_of=d("2026-08-02")))
    assert out.allowed


def test_daily_loss_limit_halts():
    out = RiskGate().evaluate(EVEN, state(equity=9_400.0, previous_equity=10_000.0))
    assert not out.allowed
    assert "daily loss" in out.vetoes[0]


def test_drawdown_limit_halts():
    out = RiskGate().evaluate(EVEN, state(equity=7_000.0, peak_equity=10_000.0,
                                          previous_equity=7_050.0))
    assert not out.allowed
    assert "drawdown" in out.vetoes[0]


def test_zero_equity_halts():
    out = RiskGate().evaluate(EVEN, state(equity=0.0))
    assert not out.allowed


def test_blocking_holds_rather_than_liquidates():
    """Empty targets mean hold. Liquidating on bad data is a trade on bad data."""
    out = RiskGate().evaluate(EVEN, state(reconciled=False))
    assert out.targets == {}
    assert out.trading_blocked is True


# --- reductions ---

def test_oversized_position_is_capped():
    gate = RiskGate(RiskLimits(max_position_weight=0.20))
    out = gate.evaluate({"A": 0.60, "B": 0.40}, state())
    assert out.targets["A"] == pytest.approx(0.20)
    assert any("capped" in v for v in out.vetoes)


def test_gross_exposure_is_scaled_not_levered():
    gate = RiskGate(RiskLimits(max_position_weight=1.0, max_gross_exposure=1.0))
    out = gate.evaluate({"A": 0.8, "B": 0.8}, state())
    assert sum(out.targets.values()) == pytest.approx(1.0)


def test_too_many_positions_are_trimmed_to_the_best():
    gate = RiskGate(RiskLimits(max_positions=2))
    out = gate.evaluate({"A": 0.1, "B": 0.5, "C": 0.3}, state())
    assert set(out.targets) == {"B", "C"}


def test_negative_weights_are_dropped_long_only():
    out = RiskGate().evaluate({"A": 0.5, "B": -0.5}, state())
    assert "B" not in out.targets


def test_empty_targets_are_allowed_and_stay_empty():
    out = RiskGate().evaluate({}, state())
    assert out.allowed
    assert out.targets == {}


# --- market-regime exposure reduction ----------------------------------


def _state(**kw):
    base = dict(equity=10_000.0, peak_equity=10_000.0, previous_equity=10_000.0,
                data_as_of=dt.date(2026, 8, 6), today=dt.date(2026, 8, 6))
    base.update(kw)
    return RiskState(**base)


def test_risk_off_empties_targets_but_still_allows_trading():
    """De-risking must EXIT, and the gate's block path means 'hold', not 'sell'.

    `trading_blocked` deliberately holds existing positions, because
    liquidating on bad data is itself a trade made on bad data. A regime veto
    is the opposite case: the data is fine and the conclusion is to be flat, so
    it empties the targets and lets the sells through.
    """
    decision = RiskGate().evaluate({"AAA": 0.5, "BBB": 0.5}, _state(risk_on=False))
    assert decision.targets == {}
    assert decision.allowed is True
    assert any("regime" in v.lower() for v in decision.vetoes)


def test_risk_on_leaves_targets_alone():
    gate = RiskGate(RiskLimits(max_position_weight=1.0))
    decision = gate.evaluate({"AAA": 0.5}, _state(risk_on=True))
    assert decision.targets == {"AAA": 0.5}


def test_regime_unset_is_not_a_veto():
    """Default None means the filter is not in use; recorded results must stand."""
    gate = RiskGate(RiskLimits(max_position_weight=1.0))
    decision = gate.evaluate({"AAA": 0.5}, _state())
    assert decision.targets == {"AAA": 0.5}
    assert not any("regime" in v.lower() for v in decision.vetoes)


def test_a_real_halt_still_beats_a_risk_on_regime():
    """Ordering matters: a halt must not be overridden by a friendly market."""
    decision = RiskGate().evaluate({"AAA": 0.5}, _state(risk_on=True, halted=True))
    assert decision.allowed is False
    assert decision.targets == {}
