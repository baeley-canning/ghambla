"""SEC EDGAR XBRL client.

EDGAR is the right source for fundamentals because every figure carries the
date it was *filed*. That maps directly onto `knowable_at`: a quarter ending
31 March is not knowable until the filing lands weeks later, and treating the
period end as the knowable date is a textbook lookahead bug.

Only annual figures are used. Trailing-twelve-month reconstruction is possible
but fiddly — most companies never file a standalone Q4, so a naive sum of four
quarters silently drops a year. Annual figures update slowly, which suits a
fundamental factor, and the rule has no special cases to get wrong.

SEC asks for a descriptive User-Agent and no more than 10 requests/second.
"""
import datetime as dt
import json
import time
import urllib.error
import urllib.request
from typing import Iterable

from .store.store import Fact

USER_AGENT = "ghambla research baeley99@gmail.com"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/{concept}.json"

# Annual reporting periods are not exactly 365 days; accept a generous band and
# reject anything that is plainly a quarter.
ANNUAL_MIN_DAYS = 300
ANNUAL_MAX_DAYS = 400

NET_INCOME = "NetIncomeLoss"
EQUITY = "StockholdersEquity"
SHARES = "WeightedAverageNumberOfDilutedSharesOutstanding"
CONCEPTS = (NET_INCOME, EQUITY, SHARES)


def parse_ticker_map(payload: dict) -> dict[str, int]:
    """Ticker -> CIK. EDGAR keys tickers with dashes for share classes."""
    out: dict[str, int] = {}
    for row in payload.values():
        ticker = str(row.get("ticker", "")).strip().upper()
        cik = row.get("cik_str")
        if ticker and isinstance(cik, int):
            out[ticker] = cik
    return out


def parse_concept(payload: dict, symbol: str, concept: str) -> list[Fact]:
    """Extract annual observations from a companyconcept response.

    Instant concepts (equity) carry no `start` and are taken as-is. Duration
    concepts (income, share counts) are kept only when the period spans roughly
    a year, so quarterly figures never get compared against annual ones.
    """
    units = payload.get("units") or {}
    rows: list[dict] = []
    for unit_rows in units.values():
        rows.extend(unit_rows or [])

    facts: list[Fact] = []
    for r in rows:
        filed, end, val, accn = r.get("filed"), r.get("end"), r.get("val"), r.get("accn")
        if not filed or not end or val is None or not accn:
            continue
        try:
            end_date = dt.date.fromisoformat(end)
            filed_date = dt.date.fromisoformat(filed)
        except ValueError:
            continue

        start = r.get("start")
        if start:
            try:
                span = (end_date - dt.date.fromisoformat(start)).days
            except ValueError:
                continue
            if not (ANNUAL_MIN_DAYS <= span <= ANNUAL_MAX_DAYS):
                continue

        facts.append(Fact(symbol=symbol, concept=concept, period_end=end_date,
                          value=float(val), knowable_at=filed_date, accn=str(accn)))
    return facts


class EdgarClient:
    def __init__(self, pause_seconds: float = 0.12) -> None:
        self._pause = pause_seconds

    def _get(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept-Encoding": "gzip, deflate"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                import gzip
                raw = gzip.decompress(raw)
        time.sleep(self._pause)
        return json.loads(raw.decode("utf-8", "replace"))

    def ticker_map(self) -> dict[str, int]:
        return parse_ticker_map(self._get(TICKERS_URL))

    def concept(self, cik: int, symbol: str, concept: str) -> list[Fact]:
        """Annual facts for one concept. A missing concept yields no facts."""
        try:
            payload = self._get(CONCEPT_URL.format(cik=cik, concept=concept))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return []  # company never reported this tag
            raise
        return parse_concept(payload, symbol, concept)


def to_edgar_ticker(symbol: str) -> str:
    """Our store uses Yahoo symbols (BRK-B); EDGAR uses the same dash form."""
    return symbol.upper()


def fetch_fundamentals(client: EdgarClient, symbols: Iterable[str],
                       concepts: Iterable[str] = CONCEPTS,
                       on_progress=None) -> tuple[list[Fact], dict[str, str]]:
    """Fetch annual facts for every symbol. Returns (facts, failures)."""
    tickers = client.ticker_map()
    facts: list[Fact] = []
    failed: dict[str, str] = {}
    symbols = list(symbols)

    for i, symbol in enumerate(symbols):
        cik = tickers.get(to_edgar_ticker(symbol))
        if cik is None:
            failed[symbol] = "no CIK on file (delisted or never SEC-registered)"
        else:
            for concept in concepts:
                try:
                    facts.extend(client.concept(cik, symbol, concept))
                except Exception as exc:
                    failed[f"{symbol}/{concept}"] = f"{type(exc).__name__}: {exc}"
        if on_progress:
            on_progress(i + 1, len(symbols), symbol)
    return facts, failed
