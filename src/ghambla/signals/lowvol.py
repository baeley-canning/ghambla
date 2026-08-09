"""Cross-sectional low-volatility signal.

The low-volatility anomaly: stocks with lower historical realised volatility
tend to deliver higher risk-adjusted returns. It is one of the most replicated
cross-sectional anomalies in the academic literature and is genuinely
independent of the other families in this harness — momentum reads the
*direction* of the price path, fundamental reads reported numbers, news reads
text; this reads only the *smoothness* of the path.

Volatility is the annualised standard deviation of daily log returns on
adjusted closes, so splits and dividends do not distort the series. The score
is highest for the calmest names: value is `1 / (1 + vol)`, which is positive,
bounded, and monotonically decreasing in volatility, so the long-only
constructor selects the low-volatility names without ever emitting a negative
score that would silently drop every symbol.

The volatility maths itself lives in `vol.py` and is shared with the allocator,
so the two consumers cannot drift apart on how volatility is measured.
"""
import datetime as dt
from typing import Sequence

from ..store.store import FeatureStore
from ..vol import TRADING_DAYS_PER_YEAR, annualised_vol
from .base import NO_OPINION, Score


class LowVolSignal:
    name = "low_vol"

    def __init__(self, lookback_days: int = 252, annualise: int = TRADING_DAYS_PER_YEAR) -> None:
        if lookback_days < 2:
            raise ValueError(f"lookback_days must be >= 2, got {lookback_days}")
        self.lookback_days = lookback_days
        self.annualise = annualise

    def score(self, store: FeatureStore, as_of: dt.date,
              universe: Sequence[str]) -> dict[str, Score]:
        history = store.bars_as_of(as_of, universe, lookback=self.lookback_days)
        out: dict[str, Score] = {}
        for symbol in universe:
            bars = history.get(symbol, [])
            if len(bars) < self.lookback_days:
                out[symbol] = NO_OPINION
                continue
            closes = [b.adj_close for b in bars]
            ann_vol = annualised_vol(closes, annualise=self.annualise)
            if ann_vol is None:
                out[symbol] = NO_OPINION
                continue
            value = 1.0 / (1.0 + ann_vol)
            out[symbol] = Score(
                value=value,
                confidence=1.0,
                rationale=(f"low-vol {ann_vol:.1%} annualised over "
                           f"{len(bars)}d -> score {value:.3f}"),
            )
        return out
