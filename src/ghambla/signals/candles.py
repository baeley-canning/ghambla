"""Candlestick pattern signal.

Candlestick patterns are pure price geometry, so they can be computed from bars
already in the store with no extra data source. The sign carries meaning: a
flipped vote turns "buy strength" into "buy weakness", which is a different
strategy that every ordering test would still pass.
"""
import datetime as dt
from typing import Sequence

from ..store.store import FeatureStore
from .base import NO_OPINION, Score


def body(bar) -> float:
    """Absolute body size."""
    return abs(bar.close - bar.open)


def candle_range(bar) -> float:
    """Full high-low range."""
    return bar.high - bar.low


def upper_shadow(bar) -> float:
    """Wick above the body."""
    return bar.high - max(bar.open, bar.close)


def lower_shadow(bar) -> float:
    """Wick below the body."""
    return min(bar.open, bar.close) - bar.low


def is_up(bar) -> bool:
    """True when the bar closed above its open."""
    return bar.close > bar.open


def is_down(bar) -> bool:
    """True when the bar closed below its open.

    Deliberately not `not is_up(...)`: a flat bar is neither up nor down, and
    treating it as down makes a directionless doji trigger a bullish pattern.
    """
    return bar.close < bar.open


def bullish_engulfing(prev, cur) -> bool:
    """Bullish engulfing: up bar fully covers prior down bar's body."""
    if candle_range(cur) == 0 or candle_range(prev) == 0:
        return False
    return (
        is_up(cur) and is_down(prev)
        and min(cur.open, cur.close) <= min(prev.open, prev.close)
        and max(cur.open, cur.close) >= max(prev.open, prev.close)
    )


def bearish_engulfing(prev, cur) -> bool:
    """Bearish engulfing: down bar fully covers prior up bar's body."""
    if candle_range(cur) == 0 or candle_range(prev) == 0:
        return False
    return (
        is_down(cur) and is_up(prev)
        and min(cur.open, cur.close) <= min(prev.open, prev.close)
        and max(cur.open, cur.close) >= max(prev.open, prev.close)
    )


def hammer(prev, cur) -> bool:
    """Hammer: long lower shadow, small upper shadow, follows a decline."""
    if candle_range(cur) == 0:
        return False
    return (
        lower_shadow(cur) >= 2 * body(cur)
        and upper_shadow(cur) <= body(cur)
        and prev.close > cur.close
    )


def shooting_star(prev, cur) -> bool:
    """Shooting star: long upper shadow, small lower shadow, follows a rise."""
    if candle_range(cur) == 0:
        return False
    return (
        upper_shadow(cur) >= 2 * body(cur)
        and lower_shadow(cur) <= body(cur)
        and prev.close < cur.close
    )


def bullish_marubozu(cur) -> bool:
    """Bullish marubozu: body nearly fills the range, closes up."""
    if candle_range(cur) == 0:
        return False
    return body(cur) >= 0.90 * candle_range(cur) and is_up(cur)


def doji(cur) -> bool:
    """Doji: tiny body relative to range. Explicitly neutral."""
    if candle_range(cur) == 0:
        return False
    return body(cur) <= 0.05 * candle_range(cur)


def pattern_votes(prev, cur) -> int:
    """Net vote for one bar pair: +1 bullish, -1 bearish, doji is 0."""
    votes = 0
    if bullish_engulfing(prev, cur):
        votes += 1
    if hammer(prev, cur):
        votes += 1
    if bullish_marubozu(cur):
        votes += 1
    if bearish_engulfing(prev, cur):
        votes -= 1
    if shooting_star(prev, cur):
        votes -= 1
    # doji is explicitly neutral and contributes 0
    return votes


class CandleSignal:
    name = "candles"

    def __init__(self, lookback_days: int = 3) -> None:
        if lookback_days < 1:
            raise ValueError(
                f"lookback_days must be at least 1, got {lookback_days=}"
            )
        self.lookback_days = lookback_days

    def score(self, store: FeatureStore, as_of: dt.date,
              universe: Sequence[str]) -> dict[str, Score]:
        # One extra bar because every pattern needs a predecessor.
        history = store.bars_as_of(
            as_of, universe, lookback=self.lookback_days + 1
        )
        out: dict[str, Score] = {}
        for symbol in universe:
            bars = history.get(symbol, [])
            if len(bars) < self.lookback_days + 1:
                out[symbol] = NO_OPINION
                continue
            total = 0
            for i in range(len(bars) - self.lookback_days, len(bars)):
                total += pattern_votes(bars[i - 1], bars[i])
            value = total / self.lookback_days
            out[symbol] = Score(
                value=value,
                confidence=1.0,
                rationale=(
                    f"candles: net {total:+d} votes over "
                    f"{self.lookback_days}d -> {value:+.3f}"
                ),
            )
        return out
