"""US large caps at daily frequency are the most arbitraged market there is and
seven candidates died there; crypto trades 24/7, is retail-dominated and less
efficient. Same discipline, different pond.
"""
import datetime as dt
import time
import urllib.request
import urllib.error
import json

from .store.store import Bar


# Real assets whose tickers end in UP or DOWN but are not leveraged tokens.
# This is maintenance debt: every new real asset with such a ticker must be
# added here. It is still better than silently dropping real assets — a false
# exclusion is invisible, a missing exclusion shows up as a weird holding in
# the journal.
REAL_UP_DOWN_BASES = frozenset({"JUP", "SYRUP", "PUMP", "UP", "DOWN"})


def parse_klines(rows: list, symbol: str) -> list[Bar]:
    """Parse Binance kline rows into Bars.

    Binance returns prices as strings; crypto has no splits or dividends to
    adjust for, so adj_close equals close — unlike every other source in this
    repo which adjusts for corporate actions.
    """
    bars: list[Bar] = []
    for row in rows:
        try:
            if len(row) < 6:
                continue
            open_time_ms = int(row[0])
            open = float(row[1])
            high = float(row[2])
            low = float(row[3])
            close = float(row[4])
            volume = float(row[5])
        except (ValueError, TypeError):
            continue
        if open <= 0 or high <= 0 or low <= 0 or close <= 0:
            continue
        date = dt.datetime.fromtimestamp(open_time_ms / 1000, tz=dt.timezone.utc).date()
        bars.append(Bar(
            symbol=symbol,
            date=date,
            open=open,
            high=high,
            low=low,
            close=close,
            adj_close=close,  # crypto has no splits or dividends to adjust for
            volume=round(volume),
        ))
    return bars


def stablecoin_or_leveraged(symbol: str) -> bool:
    """True for symbols a cross-sectional signal must not trade.

    Stablecoins have no return to rank — they sit permanently mid-pack and
    dilute every percentile. Leveraged tokens decay by construction, so
    momentum on them measures the decay, not the asset.
    """
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    base_upper = base.upper()
    stablecoin_bases = {"USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP",
                        "USDD", "PYUSD", "EURI", "USDT"}
    if base_upper in stablecoin_bases:
        return True
    if (base_upper.endswith("UP") or base_upper.endswith("DOWN")) and base_upper not in REAL_UP_DOWN_BASES:
        return True
    if len(base_upper) >= 2 and base_upper[-1] in "LS" and base_upper[-2].isdigit():
        return True
    return False


def tradable_usdt_pairs(exchange_info: dict) -> list[str]:
    """Filter Binance exchangeInfo to tradable USDT pairs.

    Keeps only spot-tradable, active pairs that are neither stablecoins nor
    leveraged tokens, so the cross-sectional signal ranks real assets only.
    """
    symbols = []
    for s in exchange_info.get("symbols", []):
        if (s.get("quoteAsset") == "USDT"
                and s.get("status") == "TRADING"
                and s.get("isSpotTradingAllowed")
                and not stablecoin_or_leveraged(s.get("symbol", ""))):
            symbols.append(s["symbol"])
    return sorted(symbols)


def dated_universe(volumes: dict[str, dict[dt.date, float]], as_of: dt.date,
                   top_n: int = 30, lookback_days: int = 30) -> list[str]:
    """Top `top_n` symbols by total volume in the window ending strictly before `as_of`.

    Membership on day D has to be decided from data knowable before D. Ranking
    on today's volume picks today's winners in advance, which is exactly the
    survivorship bias that made the equity backtest lie before it used dated
    index membership.
    """
    window_start = as_of - dt.timedelta(days=lookback_days)
    totals: dict[str, float] = {}
    for symbol, daily in volumes.items():
        total = sum(v for d, v in daily.items() if window_start <= d < as_of)
        if total > 0:
            totals[symbol] = total
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    return [s for s, _ in ranked[:top_n]]


def fetch_klines(symbol: str, start: dt.date, end: dt.date,
                 pause: float = 0.25) -> list[Bar]:
    """Fetch daily klines from Binance, paging forward until `end` or empty page.

    Network failures return what was gathered so far rather than raising, so
    a partial download still populates the store.
    """
    bars: list[Bar] = []
    current = start
    while current <= end:
        start_ms = int(dt.datetime(current.year, current.month, current.day,
                                   tzinfo=dt.timezone.utc).timestamp() * 1000)
        end_ms = int(dt.datetime(end.year, end.month, end.day,
                                 tzinfo=dt.timezone.utc).timestamp() * 1000)
        url = (f"https://api.binance.com/api/v3/klines?symbol={symbol}"
               f"&interval=1d&startTime={start_ms}&endTime={end_ms}&limit=1000")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                rows = json.loads(resp.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError):
            break
        if not rows:
            break
        page_bars = parse_klines(rows, symbol)
        bars.extend(page_bars)
        if not page_bars:
            break
        last_date = page_bars[-1].date
        if last_date >= end:
            break
        current = last_date + dt.timedelta(days=1)
        time.sleep(pause)
    return bars


def fetch_exchange_info() -> dict:
    """Fetch Binance exchange info.

    On failure return an empty symbol list so callers degrade to an empty
    universe rather than crashing.
    """
    url = "https://api.binance.com/api/v3/exchangeInfo"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError):
        return {"symbols": []}
