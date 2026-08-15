"""Live quotes for execution and reporting only.

A live quote must never reach a signal. Signals read the point-in-time store
and nothing else. A quote has no knowable_at, cannot be replayed, and would
make every backtest number unreproducible. Live quotes are for execution and
reporting only.
"""

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, Sequence

from .marktomarket import CHART_URL, USER_AGENT, TIMEOUT


@dataclass(frozen=True)
class Quote:
    symbol: str
    last: float | None
    bid: float | None
    ask: float | None
    at: datetime
    source: str

    @property
    def mid(self) -> float | None:
        """The mid price, or last when the book is unusable.

        Mid is preferred because `last` can be a stale print from an odd lot,
        while the mid is where the market is now. A crossed book (bid > ask)
        is not a usable mid — fall back to `last`.
        """
        if (
            self.bid is not None
            and self.ask is not None
            and self.bid > 0
            and self.ask > 0
            and self.bid <= self.ask
        ):
            return (self.bid + self.ask) / 2
        if self.last is not None and self.last > 0:
            return self.last
        return None


class QuoteSource(Protocol):
    name: str

    def quotes(self, symbols: Sequence[str]) -> dict[str, Quote]:
        """Return {symbol: Quote} for symbols with a usable price.

        A symbol with no usable price is simply absent from the returned dict.
        Never insert a zero or a None price — a zero reads as a total loss to
        anything downstream.
        """
        ...


def parse_yahoo_quote(payload: dict, symbol: str) -> Quote | None:
    """Parse a Yahoo chart payload into a Quote, or None when unusable.

    Zero is not a price — it reads as a total loss downstream, so a quote is
    only returned when at least one of last, bid, ask is strictly positive.
    The timestamp must be timezone-aware UTC because a naive datetime cannot
    be compared with the rest of the system's aware datetimes.
    """
    try:
        meta = payload["chart"]["result"][0]["meta"]
        last = meta.get("regularMarketPrice")
        bid = meta.get("bid")
        ask = meta.get("ask")
        if not any(
            value is not None and float(value) > 0
            for value in (last, bid, ask)
        ):
            return None
        return Quote(
            symbol=symbol,
            last=float(last) if last is not None else None,
            bid=float(bid) if bid is not None else None,
            ask=float(ask) if ask is not None else None,
            at=datetime.now(timezone.utc),
            source="yahoo",
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return None


class YahooQuoteSource:
    name = "yahoo"

    def __init__(self, pause_seconds: float = 0.15) -> None:
        self.pause_seconds = pause_seconds
        self.last_errors: dict[str, str] = {}

    def quotes(self, symbols: Sequence[str]) -> dict[str, Quote]:
        """Fetch live quotes for symbols; return {symbol: Quote}.

        Per-symbol failure is skipped, never fatal — the same rule the rest of
        ingest follows. A symbol with no usable price is simply absent from
        the returned dict. The handler is deliberately narrow: a broad catch
        turned a missing import into a silently empty feed, which reads as
        "the market has no prices" rather than "this code is broken".
        """
        self.last_errors = {}
        quotes: dict[str, Quote] = {}
        for symbol in symbols:
            url = CHART_URL.format(symbol=symbol)
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                quote = parse_yahoo_quote(payload, symbol)
                if quote is not None and quote.mid is not None:
                    quotes[symbol] = quote
            except (urllib.error.URLError, TimeoutError, OSError,
                    json.JSONDecodeError, ValueError, KeyError) as exc:
                # Per-symbol failure is skipped, never fatal.
                self.last_errors[symbol] = f"{type(exc).__name__}: {exc}"
            time.sleep(self.pause_seconds)
        return quotes
