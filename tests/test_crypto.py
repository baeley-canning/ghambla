"""Crypto universe and daily bars from a free public exchange feed.

US large caps at daily frequency are the most arbitraged market there is, and
seven candidates died there. Crypto trades 24/7, is retail-dominated, and is
demonstrably less efficient — the same anomalies have documented edges there
that are gone from equities. Same store, same point-in-time discipline, same
pre-registered gate; only the price series changes.
"""
import datetime as dt

import pytest

from ghambla.crypto import (dated_universe, parse_klines, stablecoin_or_leveraged,
                            tradable_usdt_pairs)


def _kline(ms, o, h, l, c, v):
    return [ms, str(o), str(h), str(l), str(c), str(v), ms + 86_399_999,
            "0", 0, "0", "0", "0"]


def test_parses_klines_into_bars():
    ms = int(dt.datetime(2026, 8, 1, tzinfo=dt.UTC).timestamp() * 1000)
    bars = parse_klines([_kline(ms, 100, 110, 90, 105, 1234)], "BTCUSDT")
    assert len(bars) == 1
    b = bars[0]
    assert b.symbol == "BTCUSDT" and b.date == dt.date(2026, 8, 1)
    assert (b.open, b.high, b.low, b.close) == (100.0, 110.0, 90.0, 105.0)
    assert b.adj_close == 105.0, "crypto has no splits or dividends to adjust for"


def test_malformed_rows_are_skipped_not_fatal():
    ms = int(dt.datetime(2026, 8, 1, tzinfo=dt.UTC).timestamp() * 1000)
    assert len(parse_klines([_kline(ms, 1, 2, 0.5, 1.5, 9), ["junk"], []], "X")) == 1


def test_zero_or_negative_prices_are_dropped():
    """A zero close would blow up every log return downstream."""
    ms = int(dt.datetime(2026, 8, 1, tzinfo=dt.UTC).timestamp() * 1000)
    assert parse_klines([_kline(ms, 0, 0, 0, 0, 1)], "X") == []


@pytest.mark.parametrize("sym,excluded", [
    ("BTCUSDT", False), ("ETHUSDT", False),
    ("USDCUSDT", True), ("FDUSDUSDT", True), ("TUSDUSDT", True),
    ("BTCUPUSDT", True), ("ETHDOWNUSDT", True), ("BTC3LUSDT", True),
])
def test_stablecoins_and_leveraged_tokens_are_excluded(sym, excluded):
    """A stablecoin has no return to rank, and leveraged tokens decay by design
    — both would be noise a cross-sectional signal happily trades on."""
    assert stablecoin_or_leveraged(sym) is excluded


def test_universe_is_dated_and_uses_only_prior_volume():
    """Membership on day D must be decided from data knowable before D.

    Picking today's biggest names using today's volume is the same lookahead
    that survivorship bias is in equities: it selects the winners in advance.
    """
    vols = {"AAA": {dt.date(2026, 8, 1): 100.0, dt.date(2026, 8, 2): 1.0},
            "BBB": {dt.date(2026, 8, 1): 1.0, dt.date(2026, 8, 2): 100.0}}
    chosen = dated_universe(vols, dt.date(2026, 8, 2), top_n=1, lookback_days=1)
    assert chosen == ["AAA"], "must rank on 08-01 volume, not 08-02"


def test_universe_handles_too_few_names():
    vols = {"AAA": {dt.date(2026, 8, 1): 5.0}}
    assert dated_universe(vols, dt.date(2026, 8, 2), top_n=10, lookback_days=1) == ["AAA"]


def test_filters_to_spot_usdt_pairs():
    info = {"symbols": [
        {"symbol": "BTCUSDT", "quoteAsset": "USDT", "status": "TRADING", "isSpotTradingAllowed": True},
        {"symbol": "BTCBUSD", "quoteAsset": "BUSD", "status": "TRADING", "isSpotTradingAllowed": True},
        {"symbol": "OLDUSDT", "quoteAsset": "USDT", "status": "BREAK", "isSpotTradingAllowed": True},
        {"symbol": "USDCUSDT", "quoteAsset": "USDT", "status": "TRADING", "isSpotTradingAllowed": True},
    ]}
    assert tradable_usdt_pairs(info) == ["BTCUSDT"]


@pytest.mark.parametrize("sym", ["JUPUSDT", "SYRUPUSDT", "PUMPUSDT", "UPUSDT"])
def test_real_tokens_ending_in_up_are_not_mistaken_for_leveraged(sym):
    """Binance leveraged tokens were BTCUP/ETHDOWN — a prefix plus UP/DOWN.

    A bare "ends with UP" test throws out Jupiter, Syrup and anything else whose
    ticker happens to end that way. Excluding a top-100 asset from the universe
    because of its name is a silent, permanent selection bias.
    """
    assert stablecoin_or_leveraged(sym) is False


@pytest.mark.parametrize("sym", ["BTCUPUSDT", "ETHDOWNUSDT", "ADAUPUSDT", "BTC3LUSDT", "ETH5SUSDT"])
def test_actual_leveraged_tokens_are_still_excluded(sym):
    assert stablecoin_or_leveraged(sym) is True
