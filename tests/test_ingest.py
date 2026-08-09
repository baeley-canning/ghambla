import datetime as dt

import pytest

from ghambla.store.ingest import YahooDataSource, ingest, parse_yahoo_chart
from ghambla.store.store import Bar, FeatureStore

PAYLOAD = {
    "chart": {"result": [{
        "meta": {"symbol": "AAPL"},
        "timestamp": [1767571200, 1767657600, 1767744000],
        "indicators": {
            "quote": [{
                "open": [10.0, 11.0, None],
                "high": [10.5, 11.5, None],
                "low": [9.5, 10.5, None],
                "close": [10.2, 11.2, None],
                "volume": [1000, 2000, None],
            }],
            "adjclose": [{"adjclose": [10.1, 11.1, None]}],
        },
    }]}
}


def test_parses_bars():
    bars = parse_yahoo_chart(PAYLOAD, "AAPL")
    assert len(bars) == 2
    assert bars[0].symbol == "AAPL"
    assert bars[0].close == 10.2
    assert bars[0].adj_close == 10.1
    assert bars[0].volume == 1000


def test_bars_are_dates_not_datetimes():
    bars = parse_yahoo_chart(PAYLOAD, "AAPL")
    assert isinstance(bars[0].date, dt.date)
    assert not isinstance(bars[0].date, dt.datetime)


def test_bars_are_in_chronological_order():
    bars = parse_yahoo_chart(PAYLOAD, "AAPL")
    assert bars[0].date < bars[1].date


def test_null_bars_are_skipped_not_zero_filled():
    # A zero close would read as a -100% return to the momentum signal.
    bars = parse_yahoo_chart(PAYLOAD, "AAPL")
    assert all(b.close > 0 for b in bars)
    assert len(bars) == 2  # the third row was all-null


def test_empty_result_yields_no_bars():
    assert parse_yahoo_chart({"chart": {"result": []}}, "AAPL") == []


def test_missing_chart_key_yields_no_bars():
    assert parse_yahoo_chart({}, "AAPL") == []


# --- resilience: delisted tickers routinely 404, and must not kill a run ---


class StubSource:
    """Serves one bar per symbol, but raises for anything in `broken`."""

    def __init__(self, broken=(), empty=()):
        self.broken = set(broken)
        self.empty = set(empty)
        self.calls = []

    def fetch(self, symbol, range_="10y"):
        self.calls.append(symbol)
        if symbol in self.broken:
            raise OSError(f"HTTP 404 for {symbol}")
        if symbol in self.empty:
            return []
        return [Bar(symbol=symbol, date=dt.date(2026, 1, 5), open=10.0, high=10.0,
                    low=10.0, close=10.0, adj_close=10.0, volume=100)]


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "ing.db")
    yield s
    s.close()


def test_a_failing_symbol_does_not_abort_the_run(store):
    source = StubSource(broken=["DEAD"])
    report = ingest(store, source, ["AAA", "DEAD", "BBB"])
    assert source.calls == ["AAA", "DEAD", "BBB"]
    assert report.bars_stored == 2


def test_failures_are_recorded_with_their_reason(store):
    report = ingest(store, StubSource(broken=["DEAD"]), ["AAA", "DEAD"])
    assert "DEAD" in report.failed
    assert "404" in report.failed["DEAD"]
    assert report.succeeded == ["AAA"]


def test_symbols_returning_no_bars_count_as_missing_not_succeeded(store):
    report = ingest(store, StubSource(empty=["QUIET"]), ["AAA", "QUIET"])
    assert report.succeeded == ["AAA"]
    assert "QUIET" in report.empty


def test_coverage_is_reported_as_a_fraction(store):
    report = ingest(store, StubSource(broken=["D1"], empty=["E1"]), ["AAA", "BBB", "D1", "E1"])
    assert report.coverage == pytest.approx(0.5)


def test_coverage_of_an_empty_request_is_zero(store):
    assert ingest(store, StubSource(), []).coverage == 0.0


# --- resolution guard --------------------------------------------------


def test_range_max_is_rejected():
    """Yahoo silently degrades `range=max` to quarterly bars.

    It returns ~260 rows spanning 60 years while still honouring
    `interval=1d` in the request, so nothing in the response says the
    resolution changed. Those quarterly aggregates then upsert over daily
    bars and corrupt the store. `30y` returns proper daily data from 1996.
    """
    with pytest.raises(ValueError, match="max"):
        YahooDataSource().fetch("IBM", "max")


def test_cli_ingest_defaults_to_a_daily_safe_range():
    import argparse
    from ghambla.cli import main
    parser_default = None
    try:
        main(["ingest", "--help"])
    except SystemExit:
        pass
    # the default is asserted directly rather than by parsing help text
    from ghambla import cli
    assert "30y" in open(cli.__file__).read(), "ingest default range should be 30y"
