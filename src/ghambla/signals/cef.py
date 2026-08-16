"""Closed-end fund discount signal.

The NAV series is NOT distribution-adjusted, while adj_close IS. CEFs
distribute 8-12% a year, so computing the discount from adj_close would show
it widening every year purely from dividends — an artefact that looks exactly
like a strengthening signal.

Use raw close for the price and raw close for the NAV. Never adj_close,
anywhere in this file.
"""
import datetime as dt
import statistics
from typing import Sequence

from ..cef import is_nav_symbol, nav_symbol
from ..store.store import FeatureStore
from .base import NO_OPINION, Score


class CEFDiscountSignal:
    name = "cef"

    def __init__(self, lookback_days: int = 252) -> None:
        if lookback_days < 30:
            raise ValueError(
                f"lookback_days must be at least 30, got {lookback_days=}"
            )
        self.lookback_days = lookback_days

    def score(self, store: FeatureStore, as_of: dt.date,
              universe: Sequence[str]) -> dict[str, Score]:
        out: dict[str, Score] = {}
        for symbol in universe:
            if is_nav_symbol(symbol):
                out[symbol] = NO_OPINION
                continue

            nav_sym = nav_symbol(symbol)
            symbols = [symbol, nav_sym]
            history = store.bars_as_of(
                as_of, symbols, lookback=self.lookback_days
            )

            price_bars = history.get(symbol, [])
            nav_bars = history.get(nav_sym, [])
            if len(price_bars) < self.lookback_days or len(nav_bars) < self.lookback_days:
                out[symbol] = NO_OPINION
                continue

            # Align on date, not by position: a fund and its NAV can miss
            # different days, and zipping by index would compare today's price
            # against yesterday's NAV and manufacture a discount that never
            # existed.
            price_by_date = {b.date: b.close for b in price_bars}
            nav_by_date = {b.date: b.close for b in nav_bars}
            common_dates = sorted(price_by_date.keys() & nav_by_date.keys())
            if len(common_dates) < self.lookback_days:
                out[symbol] = NO_OPINION
                continue

            discounts = []
            for d in common_dates:
                price = price_by_date[d]
                nav = nav_by_date[d]
                if price <= 0 or nav <= 0:
                    out[symbol] = NO_OPINION
                    break
                discounts.append((price / nav) - 1.0)
            else:
                if len(discounts) < self.lookback_days:
                    out[symbol] = NO_OPINION
                    continue

                mean = statistics.fmean(discounts)
                stdev = statistics.stdev(discounts)
                if stdev <= 1e-12:
                    out[symbol] = NO_OPINION
                    continue

                discount_today = discounts[-1]
                z = (discount_today - mean) / stdev
                value = -z
                out[symbol] = Score(
                    value=value,
                    confidence=1.0,
                    rationale=(
                        f"cef: discount {discount_today:+.1%}, "
                        f"z {z:+.2f} vs own {self.lookback_days}d"
                    ),
                )
                continue
            out[symbol] = NO_OPINION
        return out
