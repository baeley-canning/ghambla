"""Placebo trials — the control group for Gate 0.

Nine signals have failed the pre-registered gate. That could mean the signals
have no edge, or it could mean the gate is so severe it rejects everything,
including strategies that do carry signal. A placebo settles it: run portfolios
chosen by pure noise through the identical gate. If a meaningful fraction of
random portfolios pass, the gate cannot distinguish signal from luck and every
prior result is uninterpretable. If essentially none pass, the gate is strict
and the nine failures mean what they appear to mean.

The false-pass rate is also the number needed to interpret any future pass.
If 15% of random portfolios clear the gate, then after ten candidates a single
pass is expected by chance and means nothing on its own.
"""
import datetime as dt
import random
import statistics
from dataclasses import dataclass

from .signals.base import Score
from .walkforward import run_walk_forward, verdict


class RandomSignal:
    """Scores every symbol with a deterministic pseudo-random value.

    Must not read the store at all — it is noise by construction, and touching
    price data would make it something other than a placebo. The value is
    derived from a per-(seed, as_of, symbol) Random instance so the same seed
    and date always give the same score, making a surprising trial re-runnable
    and inspectable without depending on global random state or execution order.
    """

    name = "random"

    def __init__(self, seed: int) -> None:
        self._seed = seed

    def score(self, store, as_of: dt.date, universe) -> dict[str, Score]:
        out = {}
        for symbol in universe:
            rng = random.Random(hash((self._seed, as_of, symbol)))
            out[symbol] = Score(value=rng.uniform(-1.0, 1.0), confidence=1.0,
                                rationale="placebo random score")
        return out


@dataclass(frozen=True)
class PlaceboTrial:
    seed: int
    research_passed: int
    research_total: int
    holdout_edge: float
    holdout_passed: bool
    gate_passed: bool


@dataclass(frozen=True)
class PlaceboResult:
    trials: list[PlaceboTrial]

    @property
    def pass_rate(self) -> float:
        """Fraction of trials that cleared Gate 0; 0.0 for an empty list."""
        if not self.trials:
            return 0.0
        return sum(t.gate_passed for t in self.trials) / len(self.trials)

    @property
    def median_holdout_edge(self) -> float:
        if not self.trials:
            return 0.0
        return statistics.median(t.holdout_edge for t in self.trials)

    @property
    def best_holdout_edge(self) -> float:
        if not self.trials:
            return 0.0
        return max(t.holdout_edge for t in self.trials)


def run_placebo(store, start, end, trials: int = 30, top_n: int = 10,
                rebalance_every: int = 21, n_windows: int = 4,
                holdout_frac: float = 0.20, on_progress=None) -> PlaceboResult:
    """Run `trials` random portfolios through the identical Gate 0 walk-forward.

    Each trial uses RandomSignal(seed) with the same parameters every real
    candidate is judged by, and the verdict is computed by the same
    `ghambla.walkforward.verdict` function — no reimplementation of the gate
    logic, so the placebo measures the gate itself, not a proxy for it.
    """
    trial_results = []
    for seed in range(trials):
        signal = RandomSignal(seed)
        result = run_walk_forward(store, signal, start, end,
                                  n_windows=n_windows, holdout_frac=holdout_frac,
                                  top_n=top_n, rebalance_every=rebalance_every)
        ok, _ = verdict(result)
        research = result.research
        holdout = result.holdout
        trial = PlaceboTrial(
            seed=seed,
            research_passed=sum(w.passed for w in research),
            research_total=len(research),
            holdout_edge=holdout[-1].sharpe_edge if holdout else 0.0,
            holdout_passed=bool(holdout) and holdout[-1].passed,
            gate_passed=ok,
        )
        trial_results.append(trial)
        if on_progress is not None:
            on_progress(seed + 1, trials, trial)
    return PlaceboResult(trials=trial_results)


def format_placebo(result: PlaceboResult, gate_threshold: float) -> str:
    """Report the placebo pass rate and what it means for interpreting results.

    The numbers carry the argument: a high pass rate means the gate cannot
    distinguish signal from noise, a zero pass rate means it rejects things at
    random, and anything in between gives the expected number of candidates
    before one spurious pass.
    """
    n = len(result.trials)
    passed = sum(t.gate_passed for t in result.trials)
    rate = result.pass_rate
    lines = [
        f"Placebo trials: {n}",
        f"Gate 0 passed: {passed} ({rate:.1%})",
        f"Median holdout Sharpe edge: {result.median_holdout_edge:+.2f}",
        f"Best holdout Sharpe edge: {result.best_holdout_edge:+.2f}",
        "",
        "Research windows passed:",
    ]
    if n:
        counts = [sum(1 for t in result.trials if t.research_passed == i)
                  for i in range(max(t.research_total for t in result.trials) + 1)]
        for i, c in enumerate(counts):
            lines.append(f"  {i}: {c}")
    else:
        lines.append("  (no trials)")

    lines.append("")
    if rate == 0.0:
        lines.append("The gate rejected every random portfolio, so it is not "
                     "passing things at random.")
    elif rate > 0.10:
        lines.append(f"The gate cannot distinguish signal from noise at a "
                     f"{rate:.1%} pass rate; prior failures are uninterpretable.")
    else:
        expected = 1.0 / rate if rate > 0 else float("inf")
        lines.append(f"At a {rate:.1%} pass rate, one spurious pass is expected "
                     f"after {expected:.0f} candidates.")
    return "\n".join(lines)
