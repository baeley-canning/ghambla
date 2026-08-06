"""Value + quality fundamental signal.

Two metrics, both "higher is better", combined as equally weighted
cross-sectional z-scores:

  earnings yield = annual net income / market capitalisation   (value)
  return on equity = annual net income / shareholders' equity  (quality)

Value alone buys cheap companies, many of which are cheap because they are
failing. Quality alone buys good companies at any price. The pairing is the
standard remedy and is why neither is used on its own here.

Scores are z-scores within the universe on the day, so a positive score means
"better than the average name today" and the long-only portfolio constructor
picks from the top of that. Absolute levels are not comparable across dates,
which is fine: every decision is a cross-sectional ranking.

All inputs come through the point-in-time store keyed on SEC filing date, so a
figure is invisible until it was actually reported.
"""
import datetime as dt
import statistics
from typing import Sequence

from ..edgar import EQUITY, NET_INCOME, SHARES
from ..store.store import FeatureStore
from .base import NO_OPINION, Score

# An annual filing older than this is treated as no information rather than
# stale information. Two years covers a late filer without letting a company
# that stopped reporting look eternally cheap.
MAX_FILING_AGE_DAYS = 730


def _zscores(values: dict[str, float]) -> dict[str, float]:
    if len(values) < 2:
        return {k: 0.0 for k in values}
    xs = list(values.values())
    mean = statistics.fmean(xs)
    sd = statistics.stdev(xs)
    if sd == 0:
        return {k: 0.0 for k in values}
    return {k: (v - mean) / sd for k, v in values.items()}


class FundamentalSignal:
    name = "value_quality"

    def __init__(self, max_filing_age_days: int = MAX_FILING_AGE_DAYS) -> None:
        self.max_filing_age_days = max_filing_age_days

    def score(self, store: FeatureStore, as_of: dt.date,
              universe: Sequence[str]) -> dict[str, Score]:
        income = store.latest_fundamentals_as_of(as_of, NET_INCOME, universe)
        equity = store.latest_fundamentals_as_of(as_of, EQUITY, universe)
        shares = store.latest_fundamentals_as_of(as_of, SHARES, universe)
        bars = store.latest_bars_as_of(as_of, universe)

        earnings_yield: dict[str, float] = {}
        roe: dict[str, float] = {}

        for sym in universe:
            ni, eq, sh, bar = income.get(sym), equity.get(sym), shares.get(sym), bars.get(sym)
            if ni is None or eq is None or sh is None or bar is None:
                continue
            if (as_of - ni.knowable_at).days > self.max_filing_age_days:
                continue  # company stopped reporting
            if eq.value <= 0 or sh.value <= 0 or bar.close <= 0:
                continue  # negative book value or unusable share count
            market_cap = bar.close * sh.value
            earnings_yield[sym] = ni.value / market_cap
            roe[sym] = ni.value / eq.value

        z_value = _zscores(earnings_yield)
        z_quality = _zscores(roe)

        out: dict[str, Score] = {}
        for sym in universe:
            if sym not in z_value:
                out[sym] = NO_OPINION
                continue
            combined = 0.5 * z_value[sym] + 0.5 * z_quality[sym]
            out[sym] = Score(
                value=combined,
                confidence=1.0,
                rationale=(f"value/quality z {combined:+.2f} "
                           f"(earnings yield {earnings_yield[sym]:.1%}, "
                           f"ROE {roe[sym]:.1%})"),
            )
        return out
