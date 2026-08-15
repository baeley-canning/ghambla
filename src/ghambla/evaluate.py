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
from .papercheck import VARIANCE_EPSILON
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


@dataclass(frozen=True)
class Attribution:
    alpha_annual: float      # CAPM intercept, annualised
    beta: float
    information_ratio: float # annualised active return / tracking error
    tracking_error: float    # annualised stdev of active return
    active_return: float     # annualised mean of (strategy - benchmark)
    n_days: int


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


def align_returns(strategy_dates, strategy_equity,
                  benchmark_dates, benchmark_equity) -> tuple[list[float], list[float]]:
    """Daily returns for the dates the two series share.

    Matching on date rather than position matters because two backtests can
    skip different days; zipping by index would silently compare Monday
    against Tuesday and corrupt every downstream statistic.
    """
    strat_by_date = dict(zip(strategy_dates, strategy_equity))
    bench_by_date = dict(zip(benchmark_dates, benchmark_equity))
    common = sorted(set(strat_by_date) & set(bench_by_date))
    if len(common) < 2:
        return [], []

    strat_eq = [strat_by_date[d] for d in common]
    bench_eq = [bench_by_date[d] for d in common]
    strat_rets = [strat_eq[i] / strat_eq[i - 1] - 1.0
                  for i in range(1, len(strat_eq)) if strat_eq[i - 1] > 0]
    bench_rets = [bench_eq[i] / bench_eq[i - 1] - 1.0
                  for i in range(1, len(bench_eq)) if bench_eq[i - 1] > 0]
    return strat_rets, bench_rets


def attribution(strategy_dates, strategy_equity,
                benchmark_dates, benchmark_equity) -> Attribution:
    """CAPM-style alpha, beta, and information ratio against a benchmark.

    A zero risk-free rate is assumed, as everywhere else in this module.
    These numbers separate skill from volatility: a concentrated long-only
    portfolio carries full market beta plus idiosyncratic variance, so it can
    beat the benchmark on return while losing on Sharpe. Alpha and information
    ratio measure the active edge directly.
    """
    strat_rets, bench_rets = align_returns(strategy_dates, strategy_equity,
                                           benchmark_dates, benchmark_equity)
    n = len(strat_rets)
    if n < 3:
        return Attribution(0.0, 0.0, 0.0, 0.0, 0.0, n)

    # Beta: covariance / variance of benchmark, guarding against a constant
    # benchmark series where floating point yields a rounding-scale variance.
    m_s, m_b = statistics.fmean(strat_rets), statistics.fmean(bench_rets)
    cov = sum((s - m_s) * (b - m_b) for s, b in zip(strat_rets, bench_rets)) / (n - 1)
    var_b = sum((b - m_b) ** 2 for b in bench_rets) / (n - 1)
    if var_b <= VARIANCE_EPSILON * max(1.0, sum(b * b for b in bench_rets) / n):
        beta = 0.0
    else:
        beta = cov / var_b

    alpha = (m_s - beta * m_b) * TRADING_DAYS_PER_YEAR

    active = [s - b for s, b in zip(strat_rets, bench_rets)]
    active_return = statistics.fmean(active) * TRADING_DAYS_PER_YEAR
    tracking_error = statistics.stdev(active) * math.sqrt(TRADING_DAYS_PER_YEAR)
    information_ratio = 0.0 if tracking_error <= VARIANCE_EPSILON else active_return / tracking_error

    return Attribution(alpha_annual=alpha, beta=beta,
                       information_ratio=information_ratio,
                       tracking_error=tracking_error,
                       active_return=active_return, n_days=n)


def format_attribution(attr: Attribution) -> str:
    lines = [
        f"Beta:                    {attr.beta:.2f}",
        f"Annualised alpha:        {attr.alpha_annual:+.2%}",
        f"Information ratio:       {attr.information_ratio:.2f}",
        f"Tracking error:          {attr.tracking_error:.2%}",
        f"Aligned days:            {attr.n_days}",
    ]
    return "\n".join(lines)


def format_report(strategy: Metrics, benchmark: Metrics, benchmark_symbol: str,
                  attr: Attribution | None = None) -> str:
    """Format the Gate 0 report, optionally with diagnostic attribution.

    The attribution block is diagnostic only — it explains a Sharpe failure
    (e.g. a high-beta strategy penalised for idiosyncratic variance) but does
    not move the pre-registered Gate 0 threshold.
    """
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

    if attr is not None:
        lines.append("")
        lines.append("Attribution (diagnostic — does not affect the gate):")
        lines.append(format_attribution(attr))

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
