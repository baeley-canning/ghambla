"""Track the simulated book against live prices for a few hours.

A few hours of mark-to-market is noise, not evidence: it is recorded so the
number is real rather than guessed, not because it means anything. The
positions were chosen by signals that have failed Gate 0, so this is a
reality check on what the book is worth while the market moves, not a
validation of the strategy.
"""

import argparse
import json
import time
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

USER_AGENT = "Mozilla/5.0"
TIMEOUT = 20
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1m"


def parse_intraday_quote(payload: dict) -> tuple[float | None, str]:
    """Return (price, market_state) from a Yahoo chart payload.

    Missing or malformed data yields (None, "UNKNOWN"). NEVER return 0.0 for
    a missing price: zero would silently mark a holding to nothing and print
    a loss that did not happen.
    """
    try:
        meta = payload["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        market_state = meta.get("marketState", "UNKNOWN")
        if price is None:
            return None, "UNKNOWN"
        return float(price), str(market_state)
    except (KeyError, IndexError, TypeError, ValueError):
        return None, "UNKNOWN"


def mark_book(
    positions: dict[str, float], prices: dict[str, float], cash: float
) -> tuple[float, int, list[str]]:
    """Return (total_value, priced_count, missing_symbols).

    A holding with no price is excluded from the total but reported in
    missing_symbols — silently dropping it understates the book and reads as
    a loss that never happened.
    """
    total = cash
    priced_count = 0
    missing = []
    for symbol, shares in positions.items():
        price = prices.get(symbol)
        if price is None:
            missing.append(symbol)
        else:
            total += shares * price
            priced_count += 1
    missing.sort()
    return total, priced_count, missing


def fetch_prices(symbols, pause: float = 0.15) -> tuple[dict[str, float], str]:
    """Fetch live prices for symbols; return (price_map, most_common_state).

    Any per-symbol failure is skipped, never fatal. Sleeps `pause` between
    requests to be polite to the API.
    """
    prices: dict[str, float] = {}
    states: list[str] = []
    for symbol in symbols:
        url = CHART_URL.format(symbol=symbol)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            price, state = parse_intraday_quote(payload)
            if price is not None:
                prices[symbol] = price
            states.append(state)
        except Exception:
            # Per-symbol failure is skipped, never fatal.
            pass
        time.sleep(pause)
    if not states:
        return prices, "UNKNOWN"
    most_common = Counter(states).most_common(1)[0][0]
    return prices, most_common


def load_account(path: str) -> tuple[float, dict[str, float]]:
    """Return (cash, {symbol: shares}) from the simulated account file.

    The broker stores cost basis alongside the share count, so the position
    value is a record and not a number. A missing file, unreadable file, or
    malformed JSON yields an empty account — a monitoring tool must not take
    down the thing it monitors.
    """
    try:
        with open(path) as f:
            account = json.load(f)
        cash = float(account["cash"])
        positions: dict[str, float] = {}
        for symbol, value in account["positions"].items():
            if isinstance(value, dict):
                value = value.get("shares")
            try:
                positions[str(symbol)] = float(value)
            except (TypeError, ValueError):
                # Skip entries that cannot be coerced to a float.
                continue
        return cash, positions
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0, {}


def pnl_record(ts: str, value: float, cash: float, priced: int, missing: int,
               market_state: str, first_value: float) -> dict:
    """One sample row for the JSONL log."""
    return {
        "ts": ts,
        "value": value,
        "cash": cash,
        "priced": priced,
        "missing": missing,
        "market_state": market_state,
        "pnl": value - first_value,
    }


@dataclass(frozen=True)
class SessionSummary:
    first_value: float
    last_value: float
    pnl: float
    pct: float
    samples: int
    regular_samples: int


def session_summary(first_value: float, last_value: float, samples: int,
                    regular_samples: int) -> SessionSummary:
    """Session P/L. `pnl` is last minus first, so a fall is negative."""
    pnl = last_value - first_value
    pct = (pnl / first_value * 100) if first_value != 0 else 0.0
    return SessionSummary(
        first_value=first_value,
        last_value=last_value,
        pnl=pnl,
        pct=pct,
        samples=samples,
        regular_samples=regular_samples,
    )


def format_summary(summary: SessionSummary) -> str:
    """The final summary block, as printed today."""
    return "\n".join([
        "Final summary:",
        f"  First value: {summary.first_value:.2f}",
        f"  Last value:  {summary.last_value:.2f}",
        f"  P/L:         {summary.pnl:.2f} ({summary.pct:.2f}%)",
        f"  Samples:     {summary.samples}",
        f"  Regular session samples: {summary.regular_samples} of {summary.samples}",
    ])


def track(
    minutes: int = 180,
    every_seconds: int = 300,
    account_path: str = "data/sim_account.json",
    out_path: str = "logs/marktomarket.jsonl",
) -> None:
    """Run the mark-to-market loop for `minutes` minutes.

    Reads the simulated account, samples every `every_seconds`, appends JSON
    lines to `out_path`, and prints a final summary. If the market is not
    open, still record — but the final summary must say plainly how many
    samples were during the regular session, because a P/L measured while
    closed is not a P/L.
    """
    cash, positions = load_account(account_path)
    symbols = list(positions.keys())

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    first_value: float | None = None
    samples = 0
    regular_samples = 0
    last_value: float | None = None

    end_time = time.time() + minutes * 60
    while time.time() < end_time:
        prices, market_state = fetch_prices(symbols)
        value, priced, missing = mark_book(positions, prices, cash)
        if first_value is None:
            first_value = value
        last_value = value
        samples += 1
        if market_state == "REGULAR":
            regular_samples += 1

        record = pnl_record(
            ts=datetime.now(timezone.utc).isoformat(),
            value=value,
            cash=cash,
            priced=priced,
            missing=missing,
            market_state=market_state,
            first_value=first_value,
        )
        with open(out_path, "a") as f:
            f.write(json.dumps(record) + "\n")

        print(
            f"{record['ts']} value={value:.2f} cash={cash:.2f} "
            f"priced={priced} missing={missing} state={market_state} "
            f"pnl={record['pnl']:.2f}"
        )

        time.sleep(every_seconds)

    if first_value is None or last_value is None:
        print("No samples taken.")
        return

    summary = session_summary(
        first_value=first_value,
        last_value=last_value,
        samples=samples,
        regular_samples=regular_samples,
    )
    print("\n" + format_summary(summary))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mark the simulated book to market.")
    parser.add_argument("--minutes", type=int, default=180)
    parser.add_argument("--every-seconds", type=int, default=300)
    parser.add_argument("--account", default="data/sim_account.json")
    parser.add_argument("--out", default="logs/marktomarket.jsonl")
    args = parser.parse_args()
    track(
        minutes=args.minutes,
        every_seconds=args.every_seconds,
        account_path=args.account,
        out_path=args.out,
    )
