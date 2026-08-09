"""Diagnose whether a portfolio's drawdowns come from its holdings moving together.

This module exists to test a hypothesis, not to trade. The claim under test is
that a long-only book of ten momentum winners is a single factor bet, so
equalising individual position risk cannot fix drawdown. If the holdings are
highly correlated, the book behaves like one position wearing ten tickers, and
no amount of per-name sizing will diversify it.
"""

import math
from statistics import correlation
from typing import Sequence


def average_pairwise_correlation(series: dict[str, Sequence[float]]) -> float | None:
    """Return the mean Pearson correlation across all distinct unordered pairs.

    A series with zero variance (all values identical) has undefined correlation.
    Such series are skipped entirely — they are not treated as 0.0. Counting a
    flat series as uncorrelated would drag the average toward "diversified"
    purely because a name did not move, which is the opposite of the truth.

    Returns None if, after skipping flat series, fewer than 2 series remain, or
    if any remaining series has fewer than 2 points.
    """
    # Filter out flat series: a constant series has no variance, so its
    # correlation with anything is undefined. Including it as 0.0 would
    # falsely suggest diversification from a name that never moved.
    variable_series = {
        symbol: values
        for symbol, values in series.items()
        if len(set(values)) > 1
    }

    if len(variable_series) < 2:
        return None

    # Any remaining series must have at least 2 points for correlation to be
    # defined. A single point has no variance either, but we already filtered
    # flat series; still, a 1-point series is flat by definition, so this
    # check is defensive but explicit.
    if any(len(values) < 2 for values in variable_series.values()):
        return None

    symbols = list(variable_series.keys())
    correlations = []
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            corr = correlation(
                variable_series[symbols[i]],
                variable_series[symbols[j]],
            )
            correlations.append(corr)

    return sum(correlations) / len(correlations)


def diversification_ratio(
    weights: dict[str, float],
    vols: dict[str, float],
    portfolio_vol: float,
) -> float | None:
    """Return the ratio of weighted-average component vol to portfolio vol.

    1.0 means the book is one bet wearing several tickers: the portfolio is as
    volatile as the weighted average of its parts, so correlation ate the whole
    diversification benefit. Above 1.0 means real diversification.

    Returns None if portfolio_vol <= 0 (never divide, never return infinity),
    or if ANY symbol in weights is missing from vols. Treating an absent vol as
    zero would understate concentration, which is exactly the error this
    function exists to detect.
    """
    # NaN fails every comparison, so a bare `<= 0` guard lets it through and
    # the ratio propagates as NaN into a report that looks like a number.
    if math.isnan(portfolio_vol) or portfolio_vol <= 0:
        return None

    # A missing vol is not zero — it is unknown. Treating it as zero would
    # understate the weighted average and make the ratio look better than it
    # is, hiding concentration. Fail loudly instead.
    if any(symbol not in vols for symbol in weights):
        return None

    weighted_avg_vol = sum(weights[symbol] * vols[symbol] for symbol in weights)
    if math.isnan(weighted_avg_vol):
        return None
    return weighted_avg_vol / portfolio_vol
