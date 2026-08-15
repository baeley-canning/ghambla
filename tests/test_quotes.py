"""Tests for live quotes.

The governing rule is that a quote is execution-only. A quote has no
`knowable_at`, cannot be replayed, and would make every backtest number
unreproducible if it reached a signal. `test_cycle_quotes.py` pins that
boundary; this file pins the arithmetic.
"""
import datetime as dt

import pytest

from ghambla.quotes import Quote, YahooQuoteSource, parse_yahoo_quote

NOW = dt.datetime(2026, 8, 16, 14, 30, tzinfo=dt.UTC)


def q(last=None, bid=None, ask=None):
    return Quote(symbol="AAA", last=last, bid=bid, ask=ask, at=NOW, source="test")


# --- mid ------------------------------------------------------------------

def test_mid_is_the_midpoint_of_a_two_sided_book():
    assert q(last=99.0, bid=100.0, ask=102.0).mid == pytest.approx(101.0)


def test_mid_prefers_the_book_over_a_stale_last_print():
    """`last` can be an odd lot from minutes ago; the book is where the market
    is now. If this ever inverts, orders get sized off stale prices."""
    assert q(last=50.0, bid=100.0, ask=102.0).mid == pytest.approx(101.0)


def test_missing_book_falls_back_to_last():
    assert q(last=99.5, bid=None, ask=None).mid == pytest.approx(99.5)


def test_half_a_book_falls_back_to_last():
    assert q(last=99.5, bid=100.0, ask=None).mid == pytest.approx(99.5)
    assert q(last=99.5, bid=None, ask=100.0).mid == pytest.approx(99.5)


def test_a_crossed_book_falls_back_to_last():
    """bid > ask is a broken feed, not a 'very tight' spread."""
    assert q(last=99.5, bid=105.0, ask=100.0).mid == pytest.approx(99.5)


def test_non_positive_prices_are_not_usable():
    assert q(last=0.0, bid=0.0, ask=0.0).mid is None
    assert q(last=-5.0).mid is None
    assert q(last=None, bid=-1.0, ask=-2.0).mid is None


def test_no_price_at_all_is_none_not_zero():
    """Zero would read as a total loss to anything downstream."""
    assert q().mid is None


def test_a_zero_bid_with_a_real_last_uses_last():
    assert q(last=42.0, bid=0.0, ask=43.0).mid == pytest.approx(42.0)


# --- parsing --------------------------------------------------------------

def payload(**meta):
    return {"chart": {"result": [{"meta": meta}]}}


def test_parses_a_full_quote():
    got = parse_yahoo_quote(payload(regularMarketPrice=101.5, bid=101.0, ask=102.0), "AAA")
    assert got.symbol == "AAA"
    assert got.last == pytest.approx(101.5)
    assert got.bid == pytest.approx(101.0)
    assert got.ask == pytest.approx(102.0)
    assert got.source == "yahoo"


def test_parses_a_quote_with_no_book():
    got = parse_yahoo_quote(payload(regularMarketPrice=101.5), "AAA")
    assert got.last == pytest.approx(101.5)
    assert got.mid == pytest.approx(101.5)


def test_no_usable_price_yields_none():
    assert parse_yahoo_quote(payload(), "AAA") is None
    assert parse_yahoo_quote(payload(regularMarketPrice=0.0), "AAA") is None


def test_empty_or_malformed_payloads_yield_none():
    assert parse_yahoo_quote({}, "AAA") is None
    assert parse_yahoo_quote({"chart": {"result": []}}, "AAA") is None


def test_parsed_quote_is_timezone_aware():
    """A naive timestamp cannot be compared against anything else here."""
    got = parse_yahoo_quote(payload(regularMarketPrice=10.0), "AAA")
    assert got.at.tzinfo is not None


# --- source ---------------------------------------------------------------

class FakeSource:
    """A QuoteSource stand-in, to pin the contract the cycle relies on."""

    name = "fake"

    def __init__(self, mapping):
        self.mapping = mapping
        self.asked = []

    def quotes(self, symbols):
        self.asked.append(list(symbols))
        return {s: self.mapping[s] for s in symbols if s in self.mapping}


def test_source_omits_symbols_it_cannot_price():
    src = FakeSource({"AAA": q(last=10.0)})
    got = src.quotes(["AAA", "BBB"])
    assert "BBB" not in got
    assert got["AAA"].mid == pytest.approx(10.0)


def test_yahoo_source_declares_its_name():
    assert YahooQuoteSource().name == "yahoo"


# --- failure reporting ----------------------------------------------------
#
# The source once returned {} for every symbol because `json` was not imported
# and a bare `except Exception` swallowed the NameError. An empty feed read as
# "the market has no prices" rather than "this code is broken". The handler is
# now narrow, and failures are recorded instead of discarded.

def test_source_starts_with_no_recorded_errors():
    assert YahooQuoteSource().last_errors == {}


def test_a_programming_error_is_not_swallowed(monkeypatch):
    """A NameError or AttributeError here is a bug in this file, not a market
    condition, and must surface rather than look like an empty feed."""
    import ghambla.quotes as m

    def boom(*a, **k):
        raise AttributeError("typo in this module")

    monkeypatch.setattr(m.urllib.request, "urlopen", boom)
    with pytest.raises(AttributeError):
        YahooQuoteSource(pause_seconds=0).quotes(["AAA"])


def test_a_network_failure_is_skipped_and_recorded(monkeypatch):
    import urllib.error

    import ghambla.quotes as m

    def boom(*a, **k):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(m.urllib.request, "urlopen", boom)
    src = YahooQuoteSource(pause_seconds=0)
    assert src.quotes(["AAA", "BBB"]) == {}
    assert set(src.last_errors) == {"AAA", "BBB"}
    assert "URLError" in src.last_errors["AAA"]


def test_errors_reset_between_calls(monkeypatch):
    import urllib.error

    import ghambla.quotes as m

    calls = {"n": 0}

    def sometimes(*a, **k):
        calls["n"] += 1
        raise urllib.error.URLError("down")

    monkeypatch.setattr(m.urllib.request, "urlopen", sometimes)
    src = YahooQuoteSource(pause_seconds=0)
    src.quotes(["AAA"])
    assert set(src.last_errors) == {"AAA"}
    src.quotes(["BBB"])
    assert set(src.last_errors) == {"BBB"}, "stale errors leaked into a new call"
