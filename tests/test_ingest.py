import datetime as dt

from ghambla.store.ingest import parse_yahoo_chart

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
