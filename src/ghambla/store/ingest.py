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
from dataclasses import dataclass
from typing import Protocol, Sequence

from .store import Bar, FeatureStore, Split

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


def parse_yahoo_splits(payload: dict, symbol: str) -> list[Split]:
    """Extract split events from a chart response.

    `ratio` is new shares per old share, taken from numerator/denominator so a
    10-for-1 is 10.0.
    """
    results = payload.get("chart", {}).get("result") or []
    if not results:
        return []
    events = (results[0].get("events") or {}).get("splits") or {}

    out: list[Split] = []
    for raw in events.values():
        ts, num, den = raw.get("date"), raw.get("numerator"), raw.get("denominator")
        if ts is None or not num or not den:
            continue
        out.append(Split(symbol=symbol,
                         date=dt.datetime.fromtimestamp(ts, dt.UTC).date(),
                         ratio=float(num) / float(den)))
    return sorted(out, key=lambda s: s.date)


class YahooSplitSource:
    """Fetches only split events, at monthly resolution so payloads stay small."""

    def __init__(self, pause_seconds: float = 0.2) -> None:
        self._pause = pause_seconds

    def fetch(self, symbol: str, range_: str = "10y") -> list[Split]:
        params = urllib.parse.urlencode({"range": range_, "interval": "1mo", "events": "split"})
        req = urllib.request.Request(f"{CHART_URL}{symbol}?{params}",
                                     headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
        time.sleep(self._pause)
        return parse_yahoo_splits(payload, symbol)


def ingest_splits(store: FeatureStore, source, symbols: Sequence[str],
                  range_: str = "10y", on_progress=None) -> tuple[int, dict[str, str]]:
    total = 0
    failed: dict[str, str] = {}
    for i, symbol in enumerate(symbols):
        try:
            splits = source.fetch(symbol, range_)
        except Exception as exc:
            failed[symbol] = f"{type(exc).__name__}: {exc}"
        else:
            if splits:
                total += store.upsert_splits(splits)
        if on_progress:
            on_progress(i + 1, len(symbols), symbol)
    return total, failed


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


@dataclass(frozen=True)
class IngestReport:
    """What actually made it into the store, and what did not.

    Coverage matters for honesty, not just diagnostics: an unbiased universe
    is only unbiased if we can actually price the names that later died. A run
    that silently drops half the delisted tickers has quietly reintroduced
    survivorship bias, so the fraction gets reported and recorded.
    """
    bars_stored: int
    succeeded: list[str]
    empty: list[str]
    failed: dict[str, str]

    @property
    def requested(self) -> int:
        return len(self.succeeded) + len(self.empty) + len(self.failed)

    @property
    def coverage(self) -> float:
        return len(self.succeeded) / self.requested if self.requested else 0.0


def ingest(store: FeatureStore, source: DataSource, symbols: Sequence[str],
           range_: str = "10y", on_progress=None) -> IngestReport:
    """Fetch and store bars for each symbol, surviving individual failures.

    Delisted tickers routinely 404. Aborting the whole run on the first dead
    company would make the unbiased universe impossible to build.
    """
    total = 0
    succeeded: list[str] = []
    empty: list[str] = []
    failed: dict[str, str] = {}

    for i, symbol in enumerate(symbols):
        try:
            bars = source.fetch(symbol, range_)
        except Exception as exc:  # network, HTTP, malformed payload
            failed[symbol] = f"{type(exc).__name__}: {exc}"
        else:
            if bars:
                total += store.upsert_bars(bars)
                succeeded.append(symbol)
            else:
                empty.append(symbol)
        if on_progress:
            on_progress(i + 1, len(symbols), symbol)

    return IngestReport(bars_stored=total, succeeded=succeeded, empty=empty, failed=failed)
