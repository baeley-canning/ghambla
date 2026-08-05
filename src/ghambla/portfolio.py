"""Turn signal scores into target portfolio weights.

Phase 1 is long-only and equal-weight. Volatility scaling and per-name caps
arrive in Phase 2 alongside the risk gate.
"""
from dataclasses import dataclass

from .signals.base import Score


@dataclass(frozen=True)
class Target:
    symbol: str
    weight: float


def equal_weight_top_n(scores: dict[str, Score], n: int) -> list[Target]:
    """The `n` highest-scoring symbols, equally weighted.

    Zero-confidence scores are dropped before ranking, because abstention is
    not a bullish view. Non-positive scores are dropped because Phase 1 is
    long-only.
    """
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")

    eligible = [(sym, sc) for sym, sc in scores.items()
                if sc.confidence > 0.0 and sc.value > 0.0]
    eligible.sort(key=lambda pair: (-pair[1].value, pair[0]))
    chosen = eligible[:n]
    if not chosen:
        return []

    weight = 1.0 / len(chosen)
    return [Target(symbol=sym, weight=weight) for sym, _ in chosen]
