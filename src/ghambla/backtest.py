"""Backtest engine.

The one rule that makes this trustworthy: a decision taken on the close of
bar D executes at the OPEN of bar D+1. Filling at D's close would use a price
that did not exist when the decision was made. That single mistake is the most
common source of backtests that look profitable and are not.

Order sizing at execution time values the portfolio at the *open* we are
transacting at, never that day's close — using the close to size a trade
filled at the open would smuggle the same lookahead back in through the side
door.
"""
import datetime as dt
from dataclasses import dataclass, field
from typing import Sequence

from .costs import ibkr_tiered_commission
from .portfolio import equal_weight_top_n
from .store.store import Bar, FeatureStore

MIN_TRADE_VALUE = 1.0  # below this, an order is dust and is skipped


@dataclass(frozen=True)
class Trade:
    date: dt.date
    symbol: str
    side: str  # "BUY" or "SELL"
    shares: float
    price: float
    commission: float


@dataclass(frozen=True)
class BacktestResult:
    dates: list[dt.date] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)


def run_backtest(store: FeatureStore, signal, start: dt.date, end: dt.date,
                 initial_cash: float = 10_000.0, top_n: int = 10,
                 rebalance_every: int = 21, spread_bps: float = 5.0,
                 stale_days: int = 5) -> BacktestResult:
    dates = store.trading_dates(start, end)
    if not dates:
        return BacktestResult()

    cash = initial_cash
    positions: dict[str, float] = {}
    trades: list[Trade] = []
    equity: list[float] = []
    pending: list[tuple[str, float]] | None = None  # targets decided yesterday
    half_spread = spread_bps / 20_000.0

    for i, today in enumerate(dates):
        universe = store.universe_as_of(today)
        watched = sorted(set(universe) | set(positions))

        # 0. Cash out anything that has stopped trading. A holding whose
        #    security was acquired or delisted cannot be carried at its last
        #    close forever, or a dead company sits in the equity curve at full
        #    value. A short gap is a holiday, not a delisting, hence stale_days.
        if positions:
            still_trading = _opens_on(store, today, sorted(positions))
            last_bars = _last_bars_on(store, today, sorted(positions))
            for sym in sorted(positions):
                if sym in still_trading:
                    continue
                last = last_bars.get(sym)
                if last is None or (today - last.date).days < stale_days:
                    continue
                shares = positions.pop(sym)
                commission = ibkr_tiered_commission(shares, last.close)
                cash += shares * last.close - commission
                trades.append(Trade(date=today, symbol=sym, side="SELL", shares=shares,
                                    price=last.close, commission=commission))

        # 1. Execute yesterday's decision at TODAY's open.
        if pending is not None:
            opens = _opens_on(store, today, watched)
            targets = dict(pending)
            equity_at_open = cash + sum(sh * opens.get(sym, 0.0) for sym, sh in positions.items())

            for sym in sorted(set(positions) | set(targets)):
                px = opens.get(sym)
                if px is None or px <= 0:
                    # Not trading today (halt, delisting, missing bar). Hold.
                    continue
                want_shares = (targets.get(sym, 0.0) * equity_at_open) / px
                delta = want_shares - positions.get(sym, 0.0)
                if abs(delta * px) < MIN_TRADE_VALUE:
                    continue

                fill = px * (1 + half_spread) if delta > 0 else px * (1 - half_spread)
                commission = ibkr_tiered_commission(abs(delta), fill)

                if delta > 0 and delta * fill + commission > cash:
                    affordable = max(0.0, (cash - commission) / fill)
                    if affordable * fill < MIN_TRADE_VALUE:
                        continue
                    delta = affordable
                    commission = ibkr_tiered_commission(abs(delta), fill)

                cash -= delta * fill + commission
                positions[sym] = positions.get(sym, 0.0) + delta
                if abs(positions[sym]) < 1e-9:
                    del positions[sym]
                trades.append(Trade(date=today, symbol=sym,
                                    side="BUY" if delta > 0 else "SELL",
                                    shares=abs(delta), price=fill, commission=commission))
            pending = None

        # 2. Mark to market on today's close.
        closes = _closes_on(store, today, watched)
        equity.append(cash + sum(sh * closes.get(sym, 0.0) for sym, sh in positions.items()))

        # 3. Decide, using only data knowable as of today's close.
        if i % rebalance_every == 0 and i < len(dates) - 1 and universe:
            scores = signal.score(store, today, universe)
            pending = [(t.symbol, t.weight) for t in equal_weight_top_n(scores, top_n)]

    return BacktestResult(dates=dates, equity=equity, trades=trades)


def _closes_on(store: FeatureStore, day: dt.date, symbols: Sequence[str]) -> dict[str, float]:
    """Last known close per symbol, carrying forward if it did not trade today."""
    out = {}
    for sym, bars in store.bars_as_of(day, symbols, lookback=1).items():
        if bars:
            out[sym] = bars[-1].close
    return out


def _opens_on(store: FeatureStore, day: dt.date, symbols: Sequence[str]) -> dict[str, float]:
    """Today's open per symbol, omitting anything that did not trade today."""
    out = {}
    for sym, bars in store.bars_as_of(day, symbols, lookback=1).items():
        if bars and bars[-1].date == day:
            out[sym] = bars[-1].open
    return out


def _last_bars_on(store: FeatureStore, day: dt.date, symbols: Sequence[str]) -> dict[str, Bar]:
    """Most recent bar per symbol knowable at `day`, however old."""
    out = {}
    for sym, bars in store.bars_as_of(day, symbols, lookback=1).items():
        if bars:
            out[sym] = bars[-1]
    return out
