"""Turn signal scores into target portfolio weights.

Long-only throughout. Two schemes: equal weight, and inverse-volatility
weight. Selection is identical under both — weighting decides size, never
which names are held. Per-name concentration caps are the risk gate's job,
not this module's, so there is one place to change that policy.
"""
import statistics

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


def inverse_vol_top_n(scores: dict[str, Score], n: int,
                      vols: dict[str, float]) -> list[Target]:
    """The `n` highest-scoring symbols, weighted by inverse volatility.

    Equal weighting gives a violent name the same share as a calm one, which
    is what drives drawdown. Sizing by 1/vol equalises each position's risk
    contribution instead of its dollar amount. Treating an unknown vol as zero
    would hand it infinite weight; dropping the name would concentrate the book
    into whatever is left; the median of the chosen names is the neutral
    assumption.
    """
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")

    eligible = [(sym, sc) for sym, sc in scores.items()
                if sc.confidence > 0.0 and sc.value > 0.0]
    eligible.sort(key=lambda pair: (-pair[1].value, pair[0]))
    chosen = eligible[:n]
    if not chosen:
        return []

    usable_vols = [vols[sym] for sym, _ in chosen
                   if sym in vols and vols[sym] is not None and vols[sym] > 0.0]
    # statistics.median averages the two middle values on an even-length list;
    # indexing the upper one instead biases the stand-in toward the riskier half.
    median_vol = statistics.median(usable_vols) if usable_vols else None

    weights = []
    for sym, _ in chosen:
        vol = vols.get(sym)
        if vol is None or vol <= 0.0:
            vol = median_vol
        if vol is None:
            weights.append(1.0)
        else:
            weights.append(1.0 / vol)

    total = sum(weights)
    return [Target(symbol=sym, weight=w / total)
            for (sym, _), w in zip(chosen, weights)]
