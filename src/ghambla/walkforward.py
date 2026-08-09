"""Walk-forward evaluation — the honest Gate 0 measurement.

The design doc requires Gate 0 to be decided on *out-of-sample walk-forward
data* with a genuinely untouched holdout, not on one full-window run. A single
full-period backtest can look like an edge when it is really one lucky
sub-period, and inspecting the whole period to choose parameters turns the
"test" into the "training set".

This module splits the period into contiguous research windows plus a final
holdout that no research window may overlap, measures the strategy and the SPY
benchmark identically per window (same cost model, same next-open fills), and
applies the pre-registered verdict:

    Gate 0 passes only if a clear majority of research windows show a Sharpe
    edge of at least +0.30 with drawdown no worse than SPY, AND the holdout
    also passes.

Nothing here tunes parameters. The thresholds are module constants, set before
any result is seen, and this is the same code path every candidate signal must
survive to be considered for paper trading.
"""
import datetime as dt
from dataclasses import dataclass, field

from .backtest import run_backtest, signals_name
from .evaluate import GATE_0_SHARPE_EDGE, Metrics, buy_and_hold, compute_metrics
from .universe import BENCHMARK

HOLDOUT_FRAC_DEFAULT = 0.20
MAJORITY_FRAC = 0.50


@dataclass(frozen=True)
class WindowVerdict:
    """One walk-forward window's result and its pre-registered pass condition."""

    kind: str            # "research" | "holdout"
    start: dt.date
    end: dt.date
    strategy: Metrics
    benchmark: Metrics
    note: str = ""       # set when the window cannot be evaluated honestly

    @property
    def sharpe_edge(self) -> float:
        if self.note or self.strategy is None or self.benchmark is None:
            return 0.0
        return self.strategy.sharpe - self.benchmark.sharpe

    @property
    def drawdown_ok(self) -> bool:
        """True when the strategy's drawdown is no worse than the benchmark's.

        Drawdowns are negative fractions, so "no worse" means greater-or-equal.
        """
        if self.note or self.strategy is None or self.benchmark is None:
            return False
        return self.strategy.max_drawdown >= self.benchmark.max_drawdown

    @property
    def passed(self) -> bool:
        if self.note:
            return False
        return self.sharpe_edge >= GATE_0_SHARPE_EDGE and self.drawdown_ok


@dataclass(frozen=True)
class WalkForwardResult:
    signal_name: str
    start: dt.date
    end: dt.date
    windows: list[WindowVerdict] = field(default_factory=list)

    @property
    def research(self) -> list[WindowVerdict]:
        return [w for w in self.windows if w.kind == "research"]

    @property
    def holdout(self) -> list[WindowVerdict]:
        return [w for w in self.windows if w.kind == "holdout"]

    @property
    def passed(self) -> bool:
        return verdict(self)[0]


def verdict(result: WalkForwardResult) -> tuple[bool, list[str]]:
    """Apply the pre-registered Gate 0 walk-forward verdict.

    Returns (passed, reasons). A window with a note is automatically failed;
    a majority is *strictly more than half* of research windows, so 2-of-4 is
    a fail and never a pass.
    """
    research = result.research
    holdout = result.holdout
    reasons: list[str] = []

    if not research:
        return False, ["no research windows evaluated"]

    passed = [w for w in research if w.passed]
    majority = len(passed) / len(research) > MAJORITY_FRAC
    if not majority:
        reasons.append(
            f"{len(passed)}/{len(research)} research windows passed "
            f"(need > {MAJORITY_FRAC:.0%})")

    if not holdout:
        reasons.append("no holdout evaluated")
    elif not holdout[-1].passed:
        reasons.append("holdout failed")

    ok = majority and bool(holdout) and holdout[-1].passed
    return ok, reasons


def calendar_windows(start: dt.date, end: dt.date, n: int) -> list[tuple[dt.date, dt.date]]:
    """`n` contiguous, non-overlapping calendar slices covering [start, end].

    Integer floor division keeps the boundaries monotonic, and each window
    ends the day *before* the next begins, so no date belongs to two windows.
    Slices are calendar ranges; the actual trading dates come from the store.
    """
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    if end < start:
        raise ValueError(f"end {end} before start {start}")
    total = (end - start).days
    if total < n:
        raise ValueError(f"span of {total} days is too short for {n} windows")
    boundaries = [start + dt.timedelta(days=(i * total) // n) for i in range(n + 1)]
    out: list[tuple[dt.date, dt.date]] = []
    for i in range(n):
        a = boundaries[i]
        b = boundaries[i + 1] - dt.timedelta(days=1)
        if i == n - 1:
            b = end  # the final window covers through `end` itself
        out.append((a, b))
    return out


def run_walk_forward(store, signals, start: dt.date, end: dt.date,
                     n_windows: int = 4,
                     holdout_frac: float = HOLDOUT_FRAC_DEFAULT,
                     initial_cash: float = 10_000.0, top_n: int = 10,
                     rebalance_every: int = 21, spread_bps: float = 5.0,
                     allocator=None, weighting: str = "equal") -> WalkForwardResult:
    """Evaluate `signals` per window from `start` to `end`, plus a final holdout.

    `signals` is one signal, or a `name -> signal` mapping combined by rank —
    a combination faces exactly the same pre-registered gate as a lone signal,
    with no separate easier path.

    Research windows live strictly before the holdout, so a parameter chosen
    by looking at a research window could never have seen the holdout's data —
    the holdout is the last ~`holdout_frac` of the period and is untouched.
    """
    if not (0.0 < holdout_frac < 1.0):
        raise ValueError(f"holdout_frac must be strictly between 0 and 1, got {holdout_frac}")

    holdout_days = round((end - start).days * holdout_frac)
    holdout_start = end - dt.timedelta(days=holdout_days)
    research_end = holdout_start - dt.timedelta(days=1)

    windows: list[WindowVerdict] = []
    if research_end >= start:
        for w_start, w_end in calendar_windows(start, research_end, n_windows):
            windows.append(_evaluate_window(
                "research", store, signals, w_start, w_end,
                initial_cash, top_n, rebalance_every, spread_bps, allocator, weighting))
    if holdout_days > 0:
        windows.append(_evaluate_window(
            "holdout", store, signals, holdout_start, end,
            initial_cash, top_n, rebalance_every, spread_bps, allocator, weighting))

    return WalkForwardResult(signal_name=signals_name(signals), start=start, end=end,
                             windows=windows)


def _evaluate_window(kind, store, signals, w_start: dt.date, w_end: dt.date,
                     cash: float, top_n: int, rebalance: int,
                     spread_bps: float, allocator=None,
                     weighting: str = "equal") -> WindowVerdict:
    result = run_backtest(store, signals, w_start, w_end, initial_cash=cash,
                          top_n=top_n, rebalance_every=rebalance, spread_bps=spread_bps,
                          allocator=allocator, weighting=weighting)
    bench = buy_and_hold(store, BENCHMARK, w_start, w_end, initial_cash=cash)

    strategy = compute_metrics(result.dates, result.equity, len(result.trades))
    benchmark = compute_metrics(bench.dates, bench.equity, len(bench.trades))

    note = ""
    if len(result.dates) < 2 or len(bench.dates) < 2:
        note = "insufficient data in window"

    return WindowVerdict(kind=kind, start=w_start, end=w_end,
                         strategy=strategy, benchmark=benchmark, note=note)


def format_walk_forward(result: WalkForwardResult) -> str:
    lines = [
        f"Signal: {result.signal_name}",
        f"Period: {result.start} .. {result.end}  "
        f"({len(result.research)} research windows + {len(result.holdout)} holdout)",
        "",
    ]
    width = 24
    header = (f"{'Window':<{width}} {'Type':<9} {'Sharpe edge':>11} "
              f"{'Drawdown ok':>11}  Verdict")
    lines.append(header)
    lines.append("-" * len(header))
    for w in result.windows:
        edge = f"{w.sharpe_edge:+.2f}"
        dd = "YES" if w.drawdown_ok else "NO"
        label = f"{w.start}..{w.end}"
        if w.note:
            verdict_col = "INSUFFICIENT DATA"
        else:
            verdict_col = "PASS" if w.passed else "FAIL"
        lines.append(f"{label:<{width}} {w.kind:<9} {edge:>11} {dd:>11}  {verdict_col}")

    ok, reasons = verdict(result)
    lines.append("")
    if ok:
        lines.append("Gate 0 (walk-forward): PASS — a majority of research windows "
                     "and the holdout cleared the pre-registered thresholds.")
    else:
        detail = "; ".join(reasons) if reasons else "unknown"
        lines.append(f"Gate 0 (walk-forward): FAIL ({detail})")
        lines.append("Do not proceed to paper trading.")
    return "\n".join(lines)