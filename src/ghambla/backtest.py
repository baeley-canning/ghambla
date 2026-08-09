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
from .allocator import RankAllocator, combine_scores
from .costs import ibkr_tiered_commission
from .portfolio import equal_weight_top_n, inverse_vol_top_n
from .regime import trend_filter
from .risk import RiskState
from .store.store import FeatureStore
from .vol import realised_vols

MIN_TRADE_VALUE = 1.0  # below this, an order is dust and is skipped


def as_signal_map(signals) -> dict:
    """Accept one signal or a `name -> signal` mapping; always return a mapping."""
    if hasattr(signals, "score"):
        return {getattr(signals, "name", "signal"): signals}
    if not signals:
        raise ValueError("need at least one signal")
    return dict(signals)


def signals_name(signals) -> str:
    """Reporting label: the sub-signals' own names, joined."""
    return "+".join(s.name for s in as_signal_map(signals).values())


def score_universe(store: FeatureStore, day: dt.date, universe, signal_map: dict,
                   allocator: RankAllocator):
    """Scores for one day.

    A lone signal is scored raw. Rank-combining a single signal would centre it
    on zero, which makes half the universe positive by construction and so
    destroys the `value > 0` filter that lets momentum sit in cash through a
    drawdown. Several signals have no comparable units, so they go through the
    allocator, which ranks within each before averaging.
    """
    return combine_scores({name: sig.score(store, day, universe)
                           for name, sig in signal_map.items()}, allocator)


WEIGHTINGS = ("equal", "invvol")


def weigh(scores, top_n: int, weighting: str, store, day, vol_lookback: int) -> list:
    """Turn scores into weighted targets under the chosen scheme.

    Selection is identical under both schemes, so narrowing first changes
    nothing but cost. `realised_vols` costs one query per symbol, so pricing
    the whole universe every rebalance would be hundreds of queries to size
    ten positions.
    """
    if weighting == "equal":
        return equal_weight_top_n(scores, top_n)
    if weighting == "invvol":
        chosen = equal_weight_top_n(scores, top_n)
        vols = realised_vols(store, day, [t.symbol for t in chosen],
                             lookback=vol_lookback)
        return inverse_vol_top_n(scores, top_n, vols)
    raise ValueError(f"unknown weighting scheme: {weighting}")


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


def run_backtest(store: FeatureStore, signals, start: dt.date, end: dt.date,
                 initial_cash: float = 10_000.0, top_n: int = 10,
                 rebalance_every: int = 21, spread_bps: float = 5.0,
                 stale_days: int = 5, allocator: RankAllocator | None = None,
                 weighting: str = "equal", vol_lookback: int = 252,
                 regime_filter: bool = False, regime_lookback: int = 200,
                 risk_gate=None
                 ) -> BacktestResult:
    """`signals` is one signal, or a `name -> signal` mapping combined by rank.

    The live cycle runs every decision through `RiskGate`; the backtest never
    has. Gate 0 therefore measures a strategy that cannot be run — it reports
    a -36% drawdown that live trading would never reach, because the gate
    halts at -25%, and it reports position weights the gate would cap. When
    `risk_gate` is provided, every rebalance decision passes through it just
    as live trading would, so the backtest measures what can actually be run.
    """
    signal_map = as_signal_map(signals)
    allocator = allocator or RankAllocator()

    # Validate eagerly so a bad weighting fails before the date loop, not on
    # the first rebalance.
    if weighting not in WEIGHTINGS:
        raise ValueError(f"unknown weighting scheme: {weighting}")

    dates = store.trading_dates(start, end)
    if not dates:
        return BacktestResult()

    cash = initial_cash
    positions: dict[str, float] = {}
    trades: list[Trade] = []
    equity: list[float] = []
    pending: list[tuple[str, float]] | None = None  # targets decided yesterday
    half_spread = spread_bps / 20_000.0
    peak_equity = initial_cash
    previous_equity = initial_cash

    for i, today in enumerate(dates):
        universe = store.universe_as_of(today)
        watched = sorted(set(universe) | set(positions))

        # One read per day for the whole watchlist. `latest` carries a symbol's
        # most recent bar forward when it did not trade today, so a bar dated
        # today means "traded today" and an older one means "did not".
        latest = store.latest_bars_as_of(today, watched)

        # 0. Cash out anything that has stopped trading. A holding whose
        #    security was acquired or delisted cannot be carried at its last
        #    close forever, or a dead company sits in the equity curve at full
        #    value. A short gap is a holiday, not a delisting, hence stale_days.
        for sym in sorted(positions):
            last = latest.get(sym)
            if last is None or last.date == today:
                continue
            if (today - last.date).days < stale_days:
                continue
            shares = positions.pop(sym)
            commission = ibkr_tiered_commission(shares, last.close)
            cash += shares * last.close - commission
            trades.append(Trade(date=today, symbol=sym, side="SELL", shares=shares,
                                price=last.close, commission=commission))

        # 1. Execute yesterday's decision at TODAY's open.
        if pending is not None:
            opens = {s: b.open for s, b in latest.items() if b.date == today}
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
        equity.append(cash + sum(sh * latest[sym].close
                                 for sym, sh in positions.items() if sym in latest))

        # Track running values for the risk gate. The drawdown limit is
        # measured from the peak, so a gate given only today's equity could
        # never fire; the daily-loss limit needs yesterday's equity.
        peak_equity = max(peak_equity, equity[-1])
        # Yesterday's, deliberately: assigning today's would make the daily
        # change identically zero and silently kill `max_daily_loss`.
        previous_equity = equity[-2] if len(equity) >= 2 else equity[-1]

        # 3. Decide, using only data knowable as of today's close.
        if i % rebalance_every == 0 and i < len(dates) - 1 and universe:
            # Regime first: if the market is risk-off there is nothing to
            # score, and the book should be flat regardless of what the signal
            # thinks. `is not True`, not `is False`: trend_filter returns None
            # when it cannot be evaluated, and an unknown regime must fail
            # closed — treating "cannot tell" as "risk-on" would take full
            # exposure precisely when the data is missing.
            risk_on = trend_filter(store, today, lookback=regime_lookback) \
                if regime_filter else None

            if regime_filter and risk_on is not True:
                # `[]` means EXIT, not hold. Empty targets make the next day's
                # execution loop size every held name to zero and sell it. That
                # is the point: the book is always ~100% net long and takes the
                # market's full drawdown, so the filter must actually reduce
                # exposure. Do NOT skip the rebalance — skipping would leave
                # yesterday's targets pending and stay invested.
                pending = []
            else:
                scores = score_universe(store, today, universe, signal_map, allocator)
                targets = weigh(scores, top_n, weighting, store, today, vol_lookback)
                if risk_gate is None:
                    pending = [(t.symbol, t.weight) for t in targets]
                else:
                    state = RiskState(
                        equity=equity[-1], peak_equity=peak_equity,
                        previous_equity=previous_equity,
                        data_as_of=max((b.date for b in latest.values()), default=today),
                        today=today, risk_on=risk_on)
                    decision = risk_gate.evaluate(
                        {t.symbol: t.weight for t in targets}, state)
                    # None means "leave yesterday's decision alone and hold what
                    # you have". An empty list would size every holding to zero
                    # and liquidate — and liquidating because the gate is unhappy
                    # about data quality is itself a trade made on bad data.
                    pending = list(decision.targets.items()) if decision.allowed else None

    return BacktestResult(dates=dates, equity=equity, trades=trades)
