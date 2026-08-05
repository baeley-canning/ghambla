"""Starter universe for Phase 1.

WARNING: THIS LIST IS SURVIVORSHIP-BIASED. It is a snapshot of large-cap US
names as of 2026, so backtesting it over a ten-year history implicitly assumes
we knew in 2016 which companies would still be large in 2026. Results will be
flattering and must not be treated as evidence of an edge.

Removing this bias requires dated index-membership data, which is Phase 4
work. The store's `set_universe(effective, symbols)` already accepts dated
snapshots, so no schema change will be needed when that data arrives.
"""

BENCHMARK = "SPY"

STARTER = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "LLY", "JPM",
    "V", "UNH", "XOM", "MA", "COST", "HD", "PG", "JNJ", "ABBV", "WMT",
    "MRK", "CVX", "KO", "PEP", "ADBE", "CRM", "BAC", "TMO", "MCD", "CSCO",
]
