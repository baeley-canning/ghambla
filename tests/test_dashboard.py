"""The dashboard's data layer.

The rendering can be eyeballed; the numbers cannot. Equity history, position
values and the derived return are what a person will make decisions from, so
they get tested even though the page around them does not.
"""
import datetime as dt
import json

import pytest

from ghambla.dashboard import build_state


def _journal(tmp_path, records):
    p = tmp_path / "j.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return p


def _rec(as_of, equity, cash, positions=None, **kw):
    base = dict(as_of=as_of, cycle_started=f"{as_of}T20:00:00+00:00", mode="simulated",
                universe_size=503, signal_scores={}, allocator="rank_average",
                targets={}, risk_vetoes=[], orders=[], fills=[],
                equity=equity, cash=cash, positions=positions or {}, notes=[])
    base.update(kw)
    return base


def test_empty_journal_does_not_crash(tmp_path):
    p = tmp_path / "none.jsonl"
    state = build_state(p, tmp_path / "acct.json")
    assert state["records"] == 0
    assert state["equity"] is None


def test_equity_curve_is_chronological(tmp_path):
    p = _journal(tmp_path, [_rec("2026-08-03", 10_000.0, 100.0),
                            _rec("2026-08-01", 9_900.0, 100.0),
                            _rec("2026-08-02", 9_950.0, 100.0)])
    curve = build_state(p, tmp_path / "acct.json")["curve"]
    assert [c["date"] for c in curve] == ["2026-08-01", "2026-08-02", "2026-08-03"]


def test_return_is_measured_from_the_first_record(tmp_path):
    p = _journal(tmp_path, [_rec("2026-08-01", 10_000.0, 0.0),
                            _rec("2026-08-02", 10_500.0, 0.0)])
    assert build_state(p, tmp_path / "acct.json")["total_return"] == pytest.approx(0.05)


def test_single_record_has_zero_return_not_a_divide_by_zero(tmp_path):
    p = _journal(tmp_path, [_rec("2026-08-01", 10_000.0, 0.0)])
    assert build_state(p, tmp_path / "acct.json")["total_return"] == pytest.approx(0.0)


def test_zero_starting_equity_yields_none_not_infinity(tmp_path):
    p = _journal(tmp_path, [_rec("2026-08-01", 0.0, 0.0), _rec("2026-08-02", 500.0, 0.0)])
    assert build_state(p, tmp_path / "acct.json")["total_return"] is None


def test_halted_cycles_are_surfaced(tmp_path):
    p = _journal(tmp_path, [_rec("2026-08-01", 10_000.0, 0.0,
                                 risk_vetoes=["drawdown -26% breached limit -25%"])])
    state = build_state(p, tmp_path / "acct.json")
    assert state["latest"]["risk_vetoes"] == ["drawdown -26% breached limit -25%"]
    assert state["halted_days"] == 1


def test_positions_carry_last_known_value(tmp_path):
    p = _journal(tmp_path, [_rec("2026-08-01", 10_000.0, 500.0, positions={"AAA": 10.0})])
    pos = build_state(p, tmp_path / "acct.json")["positions"]
    assert pos[0]["symbol"] == "AAA" and pos[0]["shares"] == 10.0


def test_current_state_comes_from_the_last_written_record(tmp_path):
    """The journal is append-only, so file order is WRITE order, not date order.

    A cycle can be re-run for an earlier as_of, which leaves a record with a
    lower date written after a higher one. Current cash and positions must come
    from what was written last — that is what the broker actually holds. Taking
    the highest as_of instead makes the dashboard report a balance the account
    does not have, which is worse than showing nothing.
    """
    p = _journal(tmp_path, [_rec("2026-08-08", 10_393.87, 4_277.20, positions={"VRT": 1.0}),
                            _rec("2026-08-07", 10_075.89, 194.04,
                                 positions={s: 1.0 for s in "ABCDEFGHIJ"})])
    state = build_state(p, tmp_path / "acct.json")
    assert state["cash"] == pytest.approx(194.04), "must reflect the last write"
    assert state["latest"]["as_of"] == "2026-08-07"
    assert len(state["positions"]) == 10


def test_curve_is_still_ordered_by_date_not_by_write_order(tmp_path):
    """The chart needs chronological order even when the file is not."""
    p = _journal(tmp_path, [_rec("2026-08-08", 10_393.87, 0.0),
                            _rec("2026-08-07", 10_075.89, 0.0)])
    curve = build_state(p, tmp_path / "acct.json")["curve"]
    assert [c["date"] for c in curve] == ["2026-08-07", "2026-08-08"]
