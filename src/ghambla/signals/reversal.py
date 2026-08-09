"""Short-term reversal.

Momentum says winners keep winning over 12 months; short-term reversal says
losers bounce over days (Jegadeesh 1990, Lehmann 1990). They are opposites,
and reversal is the effect documented at this horizon.

The score is the NEGATED total return over the window. A name that fell 5%
scores +0.05 and is bought. A name that rose scores negative and is dropped by
the long-only constructor, which is what preserves the ability to sit in cash
when nothing has fallen. A reversed sign silently turns this into short-horizon
momentum, which is a different and worse strategy, and every ordering test
would still pass.
"""
import datetime as dt
from typing import Sequence

from ..store.store import FeatureStore
from .base import NO_OPINION, Score


class ReversalSignal:
    name = "reversal"

    def __init__(self, lookback_days: int = 5) -> None:
        if lookback_days < 2:
            raise ValueError(
                f"lookback_days must be at least 2, got {lookback_days=}"
            )
        self.lookback_days = lookback_days

    def score(self, store: FeatureStore, as_of: dt.date,
              universe: Sequence[str]) -> dict[str, Score]:
        history = store.bars_as_of(as_of, universe, lookback=self.lookback_days)
        out: dict[str, Score] = {}
        for symbol in universe:
            bars = history.get(symbol, [])
            if len(bars) < self.lookback_days:
                out[symbol] = NO_OPINION
                continue
            first_close = bars[0].adj_close
            last_close = bars[-1].adj_close
            if first_close <= 0:
                out[symbol] = NO_OPINION
                continue
            value = -((last_close / first_close) - 1.0)
            out[symbol] = Score(
                value=value,
                confidence=1.0,
                rationale=f"reversal: fell {-value:+.1%} over {len(bars)}d -> score {value:+.3f}",
            )
        return out
