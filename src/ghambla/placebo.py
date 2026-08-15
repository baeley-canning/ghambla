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

The placebo alone cannot distinguish a gate that rejects noise from a gate that
rejects everything. The power study supplies the complementary test: a signal
with known, tunable foresight. If the gate cannot detect even perfect foresight,
it is broken and the nine failures mean nothing. If it detects modest foresight,
the gate works and the failures mean what they appear to.
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


class OracleSignal:
    """Scores symbols by blending future returns with noise — reads the future.

    This signal deliberately reads the future and must never be used as a
    candidate. It exists only to measure the gate's detection power: if the
    gate cannot detect even perfect foresight (strength=1.0), it is broken and
    the nine failures are uninterpretable. If it detects modest foresight, the
    gate works and the failures mean what they appear to. The name makes clear
    this is not a strategy — it is a test instrument.
    """

    name = "oracle"

    def __init__(self, strength: float, horizon_days: int = 21, seed: int = 0) -> None:
        if not 0.0 <= strength <= 1.0:
            raise ValueError(f"strength must be in [0.0, 1.0], got {strength}")
        self._strength = strength
        self._horizon_days = horizon_days
        self._seed = seed

    def score(self, store, as_of: dt.date, universe) -> dict[str, Score]:
        out = {}
        for symbol in universe:
            rng = random.Random(hash((self._seed, as_of, symbol)))
            noise = rng.uniform(-1.0, 1.0)
            future_return = self._future_return(store, symbol, as_of)
            if future_return is None:
                out[symbol] = Score(value=None, confidence=0.0,
                                    rationale="no future bar available")
            else:
                value = self._strength * future_return + (1 - self._strength) * noise
                out[symbol] = Score(value=value, confidence=1.0,
                                    rationale=f"oracle blend strength={self._strength}")
        return out

    def _future_return(self, store, symbol: str, as_of: dt.date) -> float | None:
        """Return from `as_of` to `horizon_days` trading days later.

        Queries the store directly for bars after `as_of` — the point-in-time
        guarantee is being bypassed on purpose, here and nowhere else. This is
        the entire point of the oracle: it must see the future to measure
        whether the gate can detect foresight.
        """
        # Query bars strictly after as_of, ordered by date
        cur = store._conn.execute(
            "SELECT adj_close FROM bars WHERE symbol = ? AND date > ? ORDER BY date LIMIT ?",
            (symbol, as_of.isoformat(), self._horizon_days + 1),
        )
        rows = cur.fetchall()
        if len(rows) < 2:
            return None  # no future bar or not enough for a return
        start_price = rows[0]["adj_close"]
        end_price = rows[-1]["adj_close"]
        if start_price <= 0:
            return None
        return (end_price / start_price) - 1.0


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


def run_power_study(store, start, end,
                    strengths=(0.0, 0.05, 0.10, 0.25, 0.50, 1.0),
                    top_n: int = 10, rebalance_every: int = 21,
                    n_windows: int = 4, holdout_frac: float = 0.20,
                    on_progress=None) -> list[tuple[float, PlaceboTrial]]:
    """One walk-forward per strength, measuring the gate's detection power.

    Each strength uses OracleSignal(strength) through the identical Gate 0
    walk-forward every real candidate faces. The result tells us the smallest
    edge the gate can detect — if it cannot detect even strength=1.0 (perfect
    foresight), the gate is broken and the nine failures are uninterpretable.
    """
    rows = []
    total = len(strengths)
    for i, strength in enumerate(strengths):
        signal = OracleSignal(strength)
        result = run_walk_forward(store, signal, start, end,
                                  n_windows=n_windows, holdout_frac=holdout_frac,
                                  top_n=top_n, rebalance_every=rebalance_every)
        ok, _ = verdict(result)
        research = result.research
        holdout = result.holdout
        trial = PlaceboTrial(
            seed=0,
            research_passed=sum(w.passed for w in research),
            research_total=len(research),
            holdout_edge=holdout[-1].sharpe_edge if holdout else 0.0,
            holdout_passed=bool(holdout) and holdout[-1].passed,
            gate_passed=ok,
        )
        rows.append((strength, trial))
        if on_progress is not None:
            on_progress(i + 1, total, strength, trial)
    return rows


def format_power_study(rows) -> str:
    """Report which strengths pass the gate and what that means.

    The key number is the lowest strength that passes: it defines the gate's
    detection floor. If even perfect foresight fails, the gate is not a valid
    test and the prior failures are uninterpretable. Otherwise, a genuine
    effect weaker than the passing strength would go undetected.
    """
    lines = [
        f"{'Strength':>8}  {'Research':>8}  {'Holdout':>8}  {'Gate':>5}",
        f"{'':>8}  {'passed':>8}  {'edge':>8}  {'':>5}",
    ]
    passing_strengths = []
    for strength, trial in rows:
        gate = "PASS" if trial.gate_passed else "fail"
        if trial.gate_passed:
            passing_strengths.append(strength)
        lines.append(
            f"{strength:8.2f}  {trial.research_passed:>3}/{trial.research_total:<3}"
            f"  {trial.holdout_edge:+8.2f}  {gate:>5}"
        )

    lines.append("")
    if not passing_strengths:
        lines.append(
            "No strength passed, including 1.0 (perfect foresight). The gate "
            "cannot detect even perfect foresight and is therefore not a valid "
            "test — the prior failures are uninterpretable."
        )
    else:
        lowest = min(passing_strengths)
        lines.append(
            f"The lowest strength that passes is {lowest:.2f}. The gate can "
            f"detect an edge of at least that size, so a genuine effect weaker "
            f"than it would go undetected."
        )
    return "\n".join(lines)


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
