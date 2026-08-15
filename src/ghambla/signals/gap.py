"""Overnight gap reaction.

A stock that gaps up at the open tends to keep drifting up in the days that
follow — post-earnings-announcement drift says prices keep moving in the
direction of a surprise for weeks after it lands. The gap is therefore scored
positive, as continuation. Flipping this sign would turn the signal into
gap-fade, which is the opposite hypothesis and a separate candidate, not a
variation of this one.
"""
import datetime as dt
from typing import Sequence

from ..store.store import FeatureStore
from .base import NO_OPINION, Score


def overnight_gap(prev_close: float, open_price: float) -> float | None:
    """Fractional gap from the prior close to today's open."""
    if prev_close <= 0 or open_price <= 0:
        return None
    return (open_price / prev_close) - 1.0


class GapSignal:
    name = "gap"

    def __init__(self, lookback_days: int = 5, min_gap: float = 0.01) -> None:
        if lookback_days < 2:
            raise ValueError(
                f"lookback_days must be at least 2, got {lookback_days=}"
            )
        if min_gap < 0:
            raise ValueError(f"min_gap must be non-negative, got {min_gap=}")
        self.lookback_days = lookback_days
        self.min_gap = min_gap

    def score(self, store: FeatureStore, as_of: dt.date,
              universe: Sequence[str]) -> dict[str, Score]:
        history = store.bars_as_of(
            as_of, universe, lookback=self.lookback_days + 1
        )
        out: dict[str, Score] = {}
        for symbol in universe:
            bars = history.get(symbol, [])
            if len(bars) < self.lookback_days + 1:
                out[symbol] = NO_OPINION
                continue
            gaps: list[float] = []
            for prev, cur in zip(bars, bars[1:]):
                gap = overnight_gap(prev.close, cur.open)
                if gap is None:
                    continue
                # Stored prices are split-adjusted, so no split artefact guard
                # is needed; filtering large moves would discard the most
                # informative observations.
                if abs(gap) >= self.min_gap:
                    gaps.append(gap)
            if not gaps:
                out[symbol] = NO_OPINION
                continue
            value = sum(gaps) / len(gaps)
            out[symbol] = Score(
                value=value,
                confidence=1.0,
                rationale=(
                    f"gap: {len(gaps)} gap(s) over {self.lookback_days}d, "
                    f"mean {value:+.2%}"
                ),
            )
        return out
