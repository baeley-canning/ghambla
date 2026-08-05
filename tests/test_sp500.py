import datetime as dt

import pytest

from ghambla.sp500 import (
    ever_members_between,
    members_on,
    parse_membership,
    snapshot_dates,
    to_yahoo_symbol,
)

CSV = """ticker,start_date,end_date
A,2000-06-05,
AAL,1996-01-02,1997-01-15
AAL,2015-03-23,2024-09-23
AABA,1999-12-08,2017-06-19
BRK.B,2010-02-16,
ZTS,2013-06-24,
"""


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def test_parses_every_row_including_repeat_listings():
    spans = parse_membership(CSV)
    aal = [s for s in spans if s.ticker == "AAL"]
    assert len(aal) == 2


def test_open_ended_membership_has_no_end_date():
    spans = parse_membership(CSV)
    a = next(s for s in spans if s.ticker == "A")
    assert a.end is None


def test_closed_membership_keeps_its_end_date():
    spans = parse_membership(CSV)
    aaba = next(s for s in spans if s.ticker == "AABA")
    assert aaba.end == d("2017-06-19")


def test_member_during_its_span():
    spans = parse_membership(CSV)
    assert "AABA" in members_on(spans, d("2010-01-01"))


def test_not_a_member_after_removal():
    spans = parse_membership(CSV)
    assert "AABA" not in members_on(spans, d("2018-01-01"))


def test_not_a_member_before_addition():
    spans = parse_membership(CSV)
    assert "ZTS" not in members_on(spans, d("2012-01-01"))


def test_rejoining_ticker_is_absent_during_the_gap():
    spans = parse_membership(CSV)
    assert "AAL" not in members_on(spans, d("2000-01-01"))
    assert "AAL" in members_on(spans, d("2016-01-01"))
    assert "AAL" in members_on(spans, d("1996-06-01"))


def test_members_are_sorted_and_unique():
    spans = parse_membership(CSV)
    got = members_on(spans, d("2016-01-01"))
    assert got == sorted(set(got))


def test_dotted_tickers_map_to_yahoo_dashes():
    assert to_yahoo_symbol("BRK.B") == "BRK-B"
    assert to_yahoo_symbol("AAPL") == "AAPL"


def test_blank_and_malformed_rows_are_ignored():
    spans = parse_membership("ticker,start_date,end_date\n\n,,\nAAPL,notadate,\n")
    assert spans == []


def test_end_before_start_is_rejected():
    with pytest.raises(ValueError):
        parse_membership("ticker,start_date,end_date\nX,2020-01-01,2019-01-01\n")


def test_ever_members_includes_names_that_left_mid_window():
    spans = parse_membership(CSV)
    got = ever_members_between(spans, d("2016-01-01"), d("2018-01-01"))
    assert "AABA" in got  # removed 2017-06-19, inside the window


def test_ever_members_excludes_names_gone_before_the_window():
    spans = parse_membership(CSV)
    got = ever_members_between(spans, d("2016-01-01"), d("2018-01-01"))
    assert "AAL" in got  # rejoined 2015, still in
    got_late = ever_members_between(spans, d("2025-01-01"), d("2026-01-01"))
    assert "AABA" not in got_late


def test_snapshot_dates_are_month_starts():
    got = snapshot_dates(d("2026-01-15"), d("2026-04-02"))
    assert got == [d("2026-01-01"), d("2026-02-01"), d("2026-03-01"), d("2026-04-01")]


def test_snapshot_dates_roll_over_the_year():
    got = snapshot_dates(d("2025-11-05"), d("2026-02-01"))
    assert got == [d("2025-11-01"), d("2025-12-01"), d("2026-01-01"), d("2026-02-01")]
