"""Intraday mark-to-market for the open position book.

The daily cycle decides once and holds. This measures what that book is worth
while the market moves, which the daily bars cannot show — they only exist
after the close.

A few hours of mark-to-market is noise, not evidence. It is recorded so the
number is real rather than guessed, not because it means anything.
"""
import datetime as dt

import pytest

from ghambla.marktomarket import mark_book, parse_intraday_quote


def test_parses_the_last_regular_price():
    payload = {"chart": {"result": [{"meta": {"regularMarketPrice": 123.45,
                                              "marketState": "REGULAR"}}]}}
    px, state = parse_intraday_quote(payload)
    assert px == pytest.approx(123.45) and state == "REGULAR"


def test_missing_price_is_none_not_zero():
    """Zero would silently mark a holding to nothing and print a fake loss."""
    assert parse_intraday_quote({"chart": {"result": [{"meta": {}}]}})[0] is None
    assert parse_intraday_quote({})[0] is None


def test_marks_the_book_and_adds_cash():
    value, priced, missing = mark_book({"AAA": 10.0, "BBB": 5.0},
                                       {"AAA": 20.0, "BBB": 4.0}, cash=100.0)
    assert value == pytest.approx(100.0 + 200.0 + 20.0)
    assert priced == 2 and missing == []


def test_an_unpriceable_holding_is_reported_not_silently_dropped():
    """Dropping it understates the book and looks like a loss that never happened."""
    value, priced, missing = mark_book({"AAA": 10.0, "GONE": 3.0},
                                       {"AAA": 20.0}, cash=0.0)
    assert value == pytest.approx(200.0)
    assert priced == 1 and missing == ["GONE"]


def test_empty_book_is_just_cash():
    assert mark_book({}, {}, cash=250.0) == (250.0, 0, [])


def test_reads_the_real_account_shape(tmp_path):
    """SimulatedBroker stores positions as {symbol: {shares, average_cost}}.

    The first version of this module assumed {symbol: shares} and crashed on
    the real file. The test that passed had encoded the same wrong assumption,
    which is exactly how a test can be worse than no test.
    """
    import json
    from ghambla.marktomarket import load_account
    p = tmp_path / "acct.json"
    p.write_text(json.dumps({"cash": 191.74, "positions": {
        "CIEN": {"average_cost": 412.49, "shares": 2.39},
        "DELL": {"average_cost": 453.88, "shares": 2.17}}}))
    cash, positions = load_account(p)
    assert cash == pytest.approx(191.74)
    assert positions == {"CIEN": pytest.approx(2.39), "DELL": pytest.approx(2.17)}


def test_plain_shares_mapping_still_works(tmp_path):
    """Tolerate the simpler shape too rather than crashing on it."""
    import json
    from ghambla.marktomarket import load_account
    p = tmp_path / "a2.json"
    p.write_text(json.dumps({"cash": 10.0, "positions": {"AAA": 3.0}}))
    assert load_account(p)[1] == {"AAA": pytest.approx(3.0)}


def test_missing_account_file_is_empty_not_a_crash(tmp_path):
    from ghambla.marktomarket import load_account
    assert load_account(tmp_path / "nope.json") == (0.0, {})


# --- session P/L ---------------------------------------------------------
#
# These exist because a mutation battery inverted the P/L sign in two places
# and the whole suite stayed green. A loss reported as a gain is the one error
# in this module that would actually mislead someone about their money.

from ghambla.marktomarket import format_summary, pnl_record, session_summary


def test_a_falling_book_reports_a_loss():
    s = session_summary(first_value=10_000.0, last_value=9_000.0,
                        samples=5, regular_samples=5)
    assert s.pnl == pytest.approx(-1_000.0)
    assert s.pct == pytest.approx(-10.0)


def test_a_rising_book_reports_a_gain():
    s = session_summary(first_value=10_000.0, last_value=11_500.0,
                        samples=5, regular_samples=5)
    assert s.pnl == pytest.approx(1_500.0)
    assert s.pct == pytest.approx(15.0)


def test_an_unchanged_book_is_flat():
    s = session_summary(10_000.0, 10_000.0, 3, 3)
    assert s.pnl == 0.0
    assert s.pct == 0.0


def test_zero_starting_value_does_not_divide_by_zero():
    s = session_summary(first_value=0.0, last_value=500.0,
                        samples=2, regular_samples=1)
    assert s.pnl == pytest.approx(500.0)
    assert s.pct == 0.0


def test_per_sample_pnl_is_measured_against_the_session_open():
    down = pnl_record("t", value=9_800.0, cash=100.0, priced=3, missing=0,
                      market_state="REGULAR", first_value=10_000.0)
    up = pnl_record("t", value=10_200.0, cash=100.0, priced=3, missing=0,
                    market_state="REGULAR", first_value=10_000.0)
    assert down["pnl"] == pytest.approx(-200.0)
    assert up["pnl"] == pytest.approx(200.0)


def test_sample_row_keeps_the_log_schema():
    row = pnl_record("2026-08-16T00:00:00+00:00", 10_000.0, 250.0, 4, 1,
                     "CLOSED", 10_000.0)
    assert list(row) == ["ts", "value", "cash", "priced", "missing",
                         "market_state", "pnl"]
    assert row["market_state"] == "CLOSED"
    assert row["missing"] == 1


def test_a_loss_prints_with_a_minus_sign():
    """The number a human actually reads must not lose its sign."""
    text = format_summary(session_summary(10_000.0, 9_000.0, 5, 5))
    assert "P/L:         -1000.00 (-10.00%)" in text
    assert text.startswith("Final summary:")


def test_summary_reports_how_many_samples_were_in_session():
    text = format_summary(session_summary(100.0, 110.0, 10, 4))
    assert "Regular session samples: 4 of 10" in text
