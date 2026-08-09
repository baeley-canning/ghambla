"""Regime filter: price versus its 200-day simple moving average.

The parameterisation is the standard one from the tactical-allocation
literature (Faber 2007): compare price to its 200-day simple moving average.
It is deliberately NOT tuned on this dataset — a threshold picked by looking
at these results would be exactly the curve-fitting this repository exists to
catch.

WHY a trend filter is here at all: the book is always ~100% net long, so it
takes the market's full drawdown regardless of which names it holds; the
measured correlation between holdings is far too small to explain that, so
the fix has to be net exposure, not position sizing.
"""
import datetime as dt

from .universe import BENCHMARK
from .store.store import FeatureStore


def trend_filter(store: FeatureStore, as_of: dt.date,
                 symbol: str = BENCHMARK, lookback: int = 200) -> bool | None:
    """Risk-on when the last close is at or above its simple moving average.

    Reads bars only through `bars_as_of`, which enforces `knowable_at <= as_of`
    — point-in-time correctness is the property this whole system exists to
    preserve. Requires the full lookback bars; fewer means the signal cannot
    be evaluated, so return None. None means "unknown", never False — the
    caller decides how to fail, and conflating "cannot tell" with "risk-off"
    would silently move that policy into the wrong module.
    """
    # A zero lookback asks the store for nothing, satisfies `len(bars) < 0`
    # vacuously, and then divides by zero computing the average. Reject it here
    # rather than crashing three lines later.
    if lookback <= 0:
        raise ValueError(f"lookback must be positive, got {lookback}")

    history = store.bars_as_of(as_of, [symbol], lookback=lookback)
    bars = history.get(symbol, [])
    if len(bars) < lookback:
        return None
    closes = [b.adj_close for b in bars]
    avg = sum(closes) / len(closes)
    return closes[-1] >= avg
