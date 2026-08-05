"""Universe configuration.

The tradeable universe is the S&P 500 *as it stood on each date*, reconstructed
in `ghambla.sp500` from published membership spans. There is deliberately no
hard-coded list of constituents here: an as-of-today list is exactly the
survivorship bias this project exists to avoid.
"""

BENCHMARK = "SPY"

# Days of price history needed before the backtest window opens, so the 252-day
# momentum lookback is satisfied on day one. Calendar days, generously rounded
# up from 252 trading days.
WARMUP_DAYS = 400
