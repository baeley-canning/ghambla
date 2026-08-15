"""Gate 1 — paper-vs-backtest comparison.

The design doc's Gate 1 pass condition is *not* "paper made money". It is that
paper results track what the backtest predicted for the same dates: daily-return
correlation of at least 0.90 and cumulative-return divergence no greater than 3
percentage points. Divergence beyond that means the backtest was using
information the live system does not have, and the correct response is to fix
the backtest, not to trade anyway.

This module reads the journal (paper cycles) and a backtest over the identical
date range, aligns them by date, and reports the two numbers plus a verdict.
"""
import datetime as dt
import math
import statistics
from dataclasses import dataclass, field

from .backtest import run_backtest
from .journal import Journal

GATE_1_MIN_CORRELATION = 0.90
GATE_1_MAX_CUMULATIVE_DIFF = 0.03  # 3 percentage points
VARIANCE_EPSILON = 1e-12


@dataclass(frozen=True)
class PaperCheckResult:
    dates: list[dt.date] = field(default_factory=list)
    paper_returns: list[float] = field(default_factory=list)
    backtest_returns: list[float] = field(default_factory=list)
    correlation: float = 0.0
    cumulative_diff: float = 0.0
    note: str = ""

    @property
    def passed(self) -> bool:
        if self.note:
            return False
        return (self.correlation >= GATE_1_MIN_CORRELATION
                and self.cumulative_diff <= GATE_1_MAX_CUMULATIVE_DIFF)


def _daily_returns(equity: list[float]) -> list[float]:
    return [equity[i] / equity[i - 1] - 1.0
            for i in range(1, len(equity)) if equity[i - 1] > 0]


def _correlation(xs: list[float], ys: list[float]) -> float:
    """Return Pearson correlation, guarding against near-zero variance.

    An exact-zero check misses a constant series: floating point yields a
    rounding-scale denominator, and dividing two rounding-scale numbers gives
    an arbitrary correlation that Gate 1 would misread as a match.
    """
    if len(xs) < 2 or len(xs) != len(ys):
        return 0.0
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if (sxx <= VARIANCE_EPSILON * max(1.0, sum(x * x for x in xs) / len(xs)) or
            syy <= VARIANCE_EPSILON * max(1.0, sum(y * y for y in ys) / len(ys))):
        return 0.0
    return num / math.sqrt(sxx * syy)


def papercheck(journal: Journal, store, signal, start: dt.date, end: dt.date,
               initial_cash: float = 10_000.0, top_n: int = 10,
               rebalance_every: int = 21) -> PaperCheckResult:
    """Compare paper journal equity against a backtest over the same dates.

    Paper equity comes from the journal's `equity` field per cycle. The
    backtest is run over the identical date range with the identical signal
    and parameters, so any divergence is attributable to the backtest's
    assumptions, not to different inputs.
    """
    paper: dict[dt.date, float] = {}
    for record in journal.read():
        if record.get("mode") != "paper":
            continue
        as_of = dt.date.fromisoformat(record["as_of"])
        if start <= as_of <= end:
            paper[as_of] = float(record["equity"])

    if len(paper) < 2:
        return PaperCheckResult(note="fewer than 2 paper cycles in range")

    result = run_backtest(store, signal, start, end, initial_cash=initial_cash,
                          top_n=top_n, rebalance_every=rebalance_every)
    if len(result.dates) < 2:
        return PaperCheckResult(note="backtest produced no equity curve")

    # Align on dates present in both.
    bt_by_date = dict(zip(result.dates, result.equity))
    common = sorted(set(paper) & set(bt_by_date))
    if len(common) < 2:
        return PaperCheckResult(note="fewer than 2 overlapping dates")

    paper_eq = [paper[d] for d in common]
    bt_eq = [bt_by_date[d] for d in common]

    corr = _correlation(_daily_returns(paper_eq), _daily_returns(bt_eq))
    cum_diff = abs(paper_eq[-1] / paper_eq[0] - bt_eq[-1] / bt_eq[0])

    return PaperCheckResult(dates=common, paper_returns=_daily_returns(paper_eq),
                            backtest_returns=_daily_returns(bt_eq),
                            correlation=corr, cumulative_diff=cum_diff)


def format_papercheck(result: PaperCheckResult) -> str:
    lines = [
        f"Gate 1 — paper vs backtest over {len(result.dates)} overlapping dates",
        "",
    ]
    if result.note:
        lines.append(f"INSUFFICIENT DATA: {result.note}")
        lines.append("Gate 1: FAIL — cannot certify paper tracking.")
        return "\n".join(lines)

    lines.append(f"Daily-return correlation:      {result.correlation:.3f} "
                 f"(need >= {GATE_1_MIN_CORRELATION:.2f})")
    lines.append(f"Cumulative-return divergence:  {result.cumulative_diff:.2%} "
                 f"(need <= {GATE_1_MAX_CUMULATIVE_DIFF:.0%})")
    lines.append("")
    if result.passed:
        lines.append("Gate 1: PASS — paper tracks the backtest within tolerance.")
    else:
        reasons = []
        if result.correlation < GATE_1_MIN_CORRELATION:
            reasons.append("correlation below threshold")
        if result.cumulative_diff > GATE_1_MAX_CUMULATIVE_DIFF:
            reasons.append("cumulative divergence above threshold")
        lines.append(f"Gate 1: FAIL ({'; '.join(reasons)}) — "
                     "the backtest is using information the live system does not have.")
    return "\n".join(lines)
