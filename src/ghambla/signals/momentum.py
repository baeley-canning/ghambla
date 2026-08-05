"""Cross-sectional 12-1 momentum.

Total return over the last `lookback_days`, excluding the most recent
`skip_days`. The skipped month is standard practice: short-term reversal in
the latest month works against momentum.

Deliberately simple. Phase 1 exists to validate the measurement harness, not
to find an edge.
"""
import datetime as dt
from typing import Sequence

from ..store.store import FeatureStore
from .base import NO_OPINION, Score


class MomentumSignal:
    name = "momentum_12_1"

    def __init__(self, lookback_days: int = 252, skip_days: int = 21) -> None:
        if skip_days >= lookback_days:
            raise ValueError(
                f"skip_days must be smaller than lookback_days, got {skip_days=} {lookback_days=}"
            )
        self.lookback_days = lookback_days
        self.skip_days = skip_days

    def score(self, store: FeatureStore, as_of: dt.date,
              universe: Sequence[str]) -> dict[str, Score]:
        history = store.bars_as_of(as_of, universe, lookback=self.lookback_days)
        out: dict[str, Score] = {}
        for symbol in universe:
            bars = history.get(symbol, [])
            if len(bars) < self.lookback_days:
                out[symbol] = NO_OPINION
                continue
            start = bars[0].adj_close
            end = bars[-1 - self.skip_days].adj_close
            if start <= 0:
                out[symbol] = NO_OPINION
                continue
            value = (end / start) - 1.0
            out[symbol] = Score(
                value=value,
                confidence=1.0,
                rationale=(f"12-1 momentum {value:+.1%} over {self.lookback_days}d "
                           f"excluding last {self.skip_days}d"),
            )
        return out
