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
