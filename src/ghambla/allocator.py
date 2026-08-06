"""Combine several signals into one ranking.

Signals are not comparable to each other in raw units — momentum returns a
percentage, the fundamental signal returns a z-score — so they are ranked
within themselves and the ranks are averaged. Rank averaging is deliberately
crude: it is robust to one signal having fat tails, and it cannot be gamed by
a signal that emits huge numbers.

Abstention is preserved. A signal with zero confidence on a symbol does not
vote on it at all, rather than voting neutral, because "I don't know" and "I
think it's average" are different claims and conflating them lets missing data
quietly pull names toward the middle of the pack.
"""
from dataclasses import dataclass

from .signals.base import NO_OPINION, Score


@dataclass(frozen=True)
class WeightedSignal:
    name: str
    weight: float


def _ranks(scores: dict[str, Score]) -> dict[str, float]:
    """Percentile rank in [0, 1] among symbols this signal has an opinion on."""
    voted = {s: sc.value for s, sc in scores.items() if sc.confidence > 0.0}
    if not voted:
        return {}
    if len(voted) == 1:
        return {next(iter(voted)): 0.5}
    ordered = sorted(voted.items(), key=lambda kv: (kv[1], kv[0]))
    n = len(ordered) - 1
    return {sym: i / n for i, (sym, _) in enumerate(ordered)}


class RankAllocator:
    name = "rank_average"

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        """`weights` maps signal name to relative weight; default is equal."""
        self.weights = weights or {}

    def combine(self, by_signal: dict[str, dict[str, Score]]) -> dict[str, Score]:
        if not by_signal:
            return {}

        ranks = {name: _ranks(scores) for name, scores in by_signal.items()}
        universe = {sym for scores in by_signal.values() for sym in scores}

        out: dict[str, Score] = {}
        for sym in universe:
            total = 0.0
            total_weight = 0.0
            parts = []
            for name, rank_map in ranks.items():
                if sym not in rank_map:
                    continue
                w = self.weights.get(name, 1.0)
                total += w * rank_map[sym]
                total_weight += w
                parts.append(f"{name} {rank_map[sym]:.0%}")

            if total_weight == 0:
                out[sym] = NO_OPINION
                continue

            # Centre on zero so "above average" is positive, which is what the
            # long-only portfolio constructor selects on.
            combined = (total / total_weight) - 0.5
            out[sym] = Score(value=combined, confidence=1.0,
                             rationale=f"rank average {combined:+.2f} ({', '.join(parts)})")
        return out
