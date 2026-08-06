import datetime as dt

from ghambla.edgar import parse_concept, parse_ticker_map

TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
    "2": {"cik_str": None, "ticker": "BAD", "title": "Broken"},
}

INCOME = {
    "units": {"USD": [
        # annual: ~365 days -> kept
        {"start": "2024-10-01", "end": "2025-09-30", "val": 1e9,
         "accn": "a-annual", "filed": "2025-11-01", "form": "10-K"},
        # quarterly: ~91 days -> dropped
        {"start": "2025-07-01", "end": "2025-09-30", "val": 2.5e8,
         "accn": "a-q", "filed": "2025-11-01", "form": "10-Q"},
        # missing filed date -> dropped
        {"start": "2023-10-01", "end": "2024-09-30", "val": 9e8, "accn": "a-old"},
    ]}
}

EQUITY = {
    "units": {"USD": [
        # instant concept: no start, kept as-is
        {"end": "2025-09-30", "val": 5e10, "accn": "e1", "filed": "2025-11-01"},
    ]}
}


def test_ticker_map_skips_rows_without_a_cik():
    got = parse_ticker_map(TICKERS)
    assert got["AAPL"] == 320193
    assert "BAD" not in got


def test_only_annual_periods_are_kept():
    facts = parse_concept(INCOME, "AAPL", "NetIncomeLoss")
    assert len(facts) == 1
    assert facts[0].value == 1e9


def test_knowable_at_is_the_filing_date_not_the_period_end():
    facts = parse_concept(INCOME, "AAPL", "NetIncomeLoss")
    assert facts[0].period_end == dt.date(2025, 9, 30)
    assert facts[0].knowable_at == dt.date(2025, 11, 1)


def test_rows_without_a_filing_date_are_dropped():
    facts = parse_concept(INCOME, "AAPL", "NetIncomeLoss")
    assert all(f.accn != "a-old" for f in facts)


def test_instant_concepts_have_no_span_filter():
    facts = parse_concept(EQUITY, "AAPL", "StockholdersEquity")
    assert len(facts) == 1
    assert facts[0].value == 5e10


def test_empty_payload_yields_nothing():
    assert parse_concept({}, "AAPL", "NetIncomeLoss") == []
    assert parse_concept({"units": {}}, "AAPL", "NetIncomeLoss") == []


def test_unparseable_dates_are_skipped():
    payload = {"units": {"USD": [
        {"end": "not-a-date", "val": 1.0, "accn": "x", "filed": "2025-01-01"}]}}
    assert parse_concept(payload, "AAPL", "StockholdersEquity") == []
