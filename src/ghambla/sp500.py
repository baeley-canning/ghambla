"""Dated S&P 500 membership — the fix for survivorship bias.

Backtesting against today's index constituents assumes we knew years ago which
companies would still be in the index today. That single mistake inflates
returns, because the losers and the acquired simply never appear.

This module reconstructs who was actually in the index on any given date, so
the backtest can trade the names a trader could really have picked from,
including the ones that later collapsed or were bought out.

Source: fja05680/sp500, which publishes membership spans derived from S&P
announcement history. Each row is one continuous period of membership; a
ticker that left and rejoined appears more than once.
"""
import csv
import datetime as dt
import io
import urllib.request
from dataclasses import dataclass
from typing import Iterable, Sequence

MEMBERSHIP_URL = (
    "https://raw.githubusercontent.com/fja05680/sp500/master/sp500_ticker_start_end.csv"
)
USER_AGENT = "Mozilla/5.0 (compatible; ghambla research)"


@dataclass(frozen=True)
class MembershipSpan:
    ticker: str
    start: dt.date
    end: dt.date | None  # None means still a member


def to_yahoo_symbol(ticker: str) -> str:
    """S&P uses dots for share classes (BRK.B); Yahoo uses dashes (BRK-B)."""
    return ticker.replace(".", "-")


def parse_membership(csv_text: str) -> list[MembershipSpan]:
    """Parse the membership CSV.

    Rows with unparseable dates are skipped: the upstream file occasionally
    carries blanks. A row whose end precedes its start is a data error we
    refuse to guess about, so it raises.
    """
    spans: list[MembershipSpan] = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        ticker = (row.get("ticker") or "").strip()
        raw_start = (row.get("start_date") or "").strip()
        raw_end = (row.get("end_date") or "").strip()
        if not ticker or not raw_start:
            continue
        try:
            start = dt.date.fromisoformat(raw_start)
        except ValueError:
            continue
        end: dt.date | None = None
        if raw_end:
            try:
                end = dt.date.fromisoformat(raw_end)
            except ValueError:
                end = None
        if end is not None and end < start:
            raise ValueError(f"membership for {ticker} ends {end} before it starts {start}")
        spans.append(MembershipSpan(ticker=ticker, start=start, end=end))
    return spans


def members_on(spans: Iterable[MembershipSpan], day: dt.date) -> list[str]:
    """Tickers that were index members on `day`, sorted and unique."""
    return sorted({s.ticker for s in spans
                   if s.start <= day and (s.end is None or day <= s.end)})


def ever_members_between(spans: Iterable[MembershipSpan],
                         start: dt.date, end: dt.date) -> list[str]:
    """Every ticker that was a member at any point in the window.

    This is the set worth downloading price history for: anything that could
    have been held at some point during the backtest.
    """
    return sorted({s.ticker for s in spans
                   if s.start <= end and (s.end is None or s.end >= start)})


def snapshot_dates(start: dt.date, end: dt.date) -> list[dt.date]:
    """Month starts across the window, the granularity we store membership at.

    The index changes a handful of times a month, so monthly snapshots capture
    essentially all of the effect at a fraction of the storage.
    """
    out: list[dt.date] = []
    day = dt.date(start.year, start.month, 1)
    while day <= end:
        out.append(day)
        day = dt.date(day.year + 1, 1, 1) if day.month == 12 else dt.date(day.year, day.month + 1, 1)
    return out


def fetch_membership(url: str = MEMBERSHIP_URL) -> list[MembershipSpan]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return parse_membership(resp.read().decode("utf-8", "replace"))


def yahoo_symbols(tickers: Sequence[str]) -> list[str]:
    return [to_yahoo_symbol(t) for t in tickers]
