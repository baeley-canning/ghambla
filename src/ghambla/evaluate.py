"""Performance metrics and honest benchmark comparison.

Sharpe assumes a zero risk-free rate and annualises daily returns by
sqrt(252). Drawdown is peak-to-trough on the equity curve, reported as a
negative fraction.

The benchmark comparison exists because "the strategy made money" is not a
result. Beating SPY buy-and-hold after costs is the only claim worth making,
and Gate 0 of the design doc requires it by a margin.
"""
import datetime as dt
import math
import statistics
from dataclasses import dataclass

from .backtest import BacktestResult, Trade
from .costs import ibkr_tiered_commission
from .store.store import FeatureStore

TRADING_DAYS_PER_YEAR = 252
GATE_0_SHARPE_EDGE = 0.30


@dataclass(frozen=True)
class Metrics:
    total_return: float
    cagr: float
    sharpe: float
    max_drawdown: float
    n_trades: int


def compute_metrics(dates: list[dt.date], equity: list[float], n_trades: int) -> Metrics:
    if len(equity) < 2 or equity[0] <= 0:
        return Metrics(0.0, 0.0, 0.0, 0.0, n_trades)

    total_return = equity[-1] / equity[0] - 1.0

    span_days = max((dates[-1] - dates[0]).days, 1)
    years = span_days / 365.25
    cagr = (equity[-1] / equity[0]) ** (1 / years) - 1.0 if equity[-1] > 0 else -1.0

    rets = [equity[i] / equity[i - 1] - 1.0
            for i in range(1, len(equity)) if equity[i - 1] > 0]
    if len(rets) < 2:
        sharpe = 0.0
    else:
        sd = statistics.stdev(rets)
        sharpe = 0.0 if sd == 0 else (statistics.fmean(rets) / sd) * math.sqrt(TRADING_DAYS_PER_YEAR)

    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            max_dd = min(max_dd, e / peak - 1.0)

    return Metrics(total_return=total_return, cagr=cagr, sharpe=sharpe,
                   max_drawdown=max_dd, n_trades=n_trades)


def buy_and_hold(store: FeatureStore, symbol: str, start: dt.date, end: dt.date,
                 initial_cash: float = 10_000.0) -> BacktestResult:
    """Benchmark: buy at the first available open, hold to the end."""
    dates = store.trading_dates(start, end)
    if not dates:
        return BacktestResult()

    first = store.bars_as_of(dates[0], [symbol], lookback=1)[symbol]
    if not first or first[-1].open <= 0:
        return BacktestResult()
    entry = first[-1].open
    commission = ibkr_tiered_commission(initial_cash / entry, entry)
    shares = (initial_cash - commission) / entry

    equity, kept = [], []
    for day in dates:
        bars = store.bars_as_of(day, [symbol], lookback=1)[symbol]
        if bars:
            equity.append(shares * bars[-1].close)
            kept.append(day)

    trade = Trade(date=dates[0], symbol=symbol, side="BUY", shares=shares,
                  price=entry, commission=commission)
    return BacktestResult(dates=kept, equity=equity, trades=[trade])


def format_report(strategy: Metrics, benchmark: Metrics, benchmark_symbol: str) -> str:
    rows = [
        ("Total return", f"{strategy.total_return:+.2%}", f"{benchmark.total_return:+.2%}"),
        ("CAGR", f"{strategy.cagr:+.2%}", f"{benchmark.cagr:+.2%}"),
        ("Sharpe", f"{strategy.sharpe:.2f}", f"{benchmark.sharpe:.2f}"),
        ("Max drawdown", f"{strategy.max_drawdown:.2%}", f"{benchmark.max_drawdown:.2%}"),
        ("Trades", str(strategy.n_trades), str(benchmark.n_trades)),
    ]
    width = max(len(r[0]) for r in rows)
    lines = [f"{'Metric':<{width}}  {'Strategy':>12}  {benchmark_symbol:>12}",
             "-" * (width + 28)]
    lines += [f"{name:<{width}}  {a:>12}  {b:>12}" for name, a, b in rows]

    edge = strategy.sharpe - benchmark.sharpe
    drawdown_ok = strategy.max_drawdown >= benchmark.max_drawdown
    lines.append("")
    lines.append(f"Sharpe edge over {benchmark_symbol}: {edge:+.2f}"
                 f"  (need >= {GATE_0_SHARPE_EDGE:+.2f})")
    if edge >= GATE_0_SHARPE_EDGE and drawdown_ok:
        lines.append("Gate 0: PASS — Sharpe edge met and drawdown no worse than benchmark.")
    else:
        reasons = []
        if edge < GATE_0_SHARPE_EDGE:
            reasons.append("Sharpe edge below threshold")
        if not drawdown_ok:
            reasons.append("drawdown worse than benchmark")
        lines.append(f"Gate 0: FAIL ({'; '.join(reasons)}) — do not proceed to paper trading.")
    return "\n".join(lines)
