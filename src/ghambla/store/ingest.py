"""Historical data ingest.

Phase 1 uses the Yahoo Finance chart endpoint: free, no key, ten years of
daily bars with adjusted closes. It is an unofficial endpoint, so it is
isolated behind `DataSource` and will be replaced by IBKR historical data in
Phase 3, when an account exists and the broker becomes the authoritative
source.
"""
import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from typing import Protocol, Sequence

from .store import Bar, FeatureStore

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
USER_AGENT = "Mozilla/5.0 (compatible; ghambla research)"


class DataSource(Protocol):
    def fetch(self, symbol: str, range_: str = "10y") -> list[Bar]: ...


def parse_yahoo_chart(payload: dict, symbol: str) -> list[Bar]:
    """Convert a decoded chart response into bars.

    Pure function over an already-decoded dict so it can be tested without a
    network call. Rows with any null field are skipped rather than zero-filled:
    a zero close would look like a -100% return to a momentum signal.
    """
    results = payload.get("chart", {}).get("result") or []
    if not results:
        return []
    r = results[0]
    stamps = r.get("timestamp") or []
    quote = (r.get("indicators", {}).get("quote") or [{}])[0]
    adj_block = (r.get("indicators", {}).get("adjclose") or [{}])[0]
    adj = adj_block.get("adjclose") or []

    bars: list[Bar] = []
    for i, ts in enumerate(stamps):
        row = [(quote.get(k) or [None] * len(stamps))[i]
               for k in ("open", "high", "low", "close", "volume")]
        adj_close = adj[i] if i < len(adj) else None
        if any(v is None for v in row) or adj_close is None:
            continue
        o, h, lo, c, v = row
        bars.append(Bar(
            symbol=symbol,
            date=dt.datetime.fromtimestamp(ts, dt.UTC).date(),
            open=float(o), high=float(h), low=float(lo), close=float(c),
            adj_close=float(adj_close), volume=int(v),
        ))
    return bars


class YahooDataSource:
    def __init__(self, pause_seconds: float = 0.5) -> None:
        self._pause = pause_seconds

    def fetch(self, symbol: str, range_: str = "10y") -> list[Bar]:
        params = urllib.parse.urlencode({"range": range_, "interval": "1d", "events": "div,split"})
        req = urllib.request.Request(f"{CHART_URL}{symbol}?{params}",
                                     headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
        time.sleep(self._pause)  # be polite to an endpoint we do not pay for
        return parse_yahoo_chart(payload, symbol)


def ingest(store: FeatureStore, source: DataSource, symbols: Sequence[str],
           range_: str = "10y") -> int:
    total = 0
    for symbol in symbols:
        bars = source.fetch(symbol, range_)
        total += store.upsert_bars(bars)
    return total
