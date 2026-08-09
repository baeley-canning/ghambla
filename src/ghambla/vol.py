"""Shared realised-volatility maths.

The low-vol signal and the portfolio allocator both need the same
realised-volatility calculation: annualised standard deviation of daily log
returns on adjusted closes. Keeping it in one module means the two consumers
cannot drift apart — a change to how volatility is measured (e.g. a different
annualisation factor, or a different return definition) lands in exactly one
place and both pick it up.
"""
import datetime as dt
import math
import statistics
from typing import Sequence

from .store.store import FeatureStore

TRADING_DAYS_PER_YEAR = 252


def annualised_vol(closes: Sequence[float],
                   annualise: int = TRADING_DAYS_PER_YEAR) -> float | None:
    """Annualised standard deviation of daily log returns.

    Returns None when the series is too short or contains non-positive prices —
    a missing volatility must not read as zero, which would imply a risk-free
    asset.
    """
    if len(closes) < 2:
        return None
    if any(c <= 0 for c in closes):
        return None
    rets = [math.log(closes[i] / closes[i - 1])
            for i in range(1, len(closes))]
    if len(rets) < 2:
        return None
    sd = statistics.stdev(rets)
    return sd * math.sqrt(annualise)


def realised_vols(store: FeatureStore, day: dt.date,
                  symbols: Sequence[str],
                  lookback: int = TRADING_DAYS_PER_YEAR) -> dict[str, float]:
    """Realised volatility for each symbol as of a point in time.

    Reads bars only through `bars_as_of`, which enforces `knowable_at <= day` —
    point-in-time correctness is the property this whole system exists to
    preserve. Symbols with fewer than the full lookback bars, or whose
    volatility is unknown, are omitted entirely rather than reported as zero.
    """
    history = store.bars_as_of(day, symbols, lookback=lookback)
    out: dict[str, float] = {}
    for symbol in symbols:
        bars = history.get(symbol, [])
        if len(bars) < lookback:
            continue
        closes = [b.adj_close for b in bars]
        vol = annualised_vol(closes)
        if vol is not None:
            out[symbol] = vol
    return out
