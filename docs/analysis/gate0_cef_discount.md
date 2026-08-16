# Candidate 11: closed-end fund discount — pre-registration

**Written and committed before the signal exists.** No discount result has been
computed. `git log` shows this file landing before `src/ghambla/signals/cef.py`.

## Why this is different from candidates 1-10

Every previous candidate was a **price pattern** on US large caps: momentum,
value, low-vol, reversal, news, candlesticks, gap. All ten sit inside the noise
distribution measured by the placebo study, on the most analysed market on
earth. That question is answered and is not being asked again.

This one is not a price pattern. A closed-end fund has a **published net asset
value**, so the gap between price and NAV is an observable number rather than
an inferred one. The strategy is buying a dollar of assets for less than a
dollar, and waiting.

**The mechanism that protects it from arbitrage is structural.** A CEF has no
redemption mechanism — you cannot create or destroy shares to close the gap,
the way an ETF authorised participant can. Forcing convergence requires
activism, a tender, an open-ending or a liquidation. Most of these funds are
$100m-$500m, which is too small for an institution to move and too operationally
awkward to be worth their time. That is precisely the capacity constraint a
retail account is unencumbered by.

## Data — verified before writing this

Yahoo publishes CEF NAV history under the Nasdaq `X<ticker>X` convention.
Checked against 40 well-known funds: **32 have 10 years of daily price and NAV**
(2,514 bars each). Current discounts range from -11.7% (RVT) to +108.7% (GUT),
so the cross-sectional dispersion is real and wide.

## The signal, fixed now

Absolute discount is **not** comparable across funds. GUT has traded at a large
premium for years and RVT at a persistent discount; ranking on the raw level
would simply sort funds by their own permanent character and buy the same names
forever.

The signal is therefore the **z-score of a fund's current discount against its
own trailing history**:

```
discount        = (price / nav) - 1                 # both RAW, see below
z               = (discount - mean(discount, 252d)) / stdev(discount, 252d)
score           = -z
```

Negated, so a discount unusually *wide* for that fund scores positive and is
bought. A fund at its own normal level scores zero.

- Lookback: **252 trading days**, fixed.
- A fund with fewer than 252 observations abstains (`NO_OPINION`).
- A fund whose trailing discount standard deviation is at or below
  `VARIANCE_EPSILON` abstains — a constant discount has no deviation to measure
  and dividing by rounding noise gives an arbitrary z.
- NAV or price ≤ 0 abstains.

### The correctness trap, recorded before it can be discovered later

The NAV series is **not** distribution-adjusted, while `adj_close` **is**. CEFs
pay large distributions — often 8-12% a year. Computing the discount as
`adj_close / nav` would therefore show the gap widening every year purely from
dividends, which is an artefact and not a discount.

**The discount must be computed from raw `close` against raw NAV.** Backtest
returns continue to use `adj_close` as everywhere else, because those genuinely
are total returns. Two different price fields, on purpose, for two different
questions.

## Universe

The 32 verified funds, stored as a dated universe like every other candidate.

**This universe is survivorship-biased and the bias is not fixable here.** The
list is funds that exist in 2026; CEFs that merged, liquidated or open-ended are
absent, and open-ending is exactly the event that closes a discount profitably.
The bias therefore runs in the strategy's *favour* on the exit side and against
it on the failure side, and the net direction is genuinely unclear. It is
recorded here so that a pass cannot later be presented as clean.

32 names is also a small cross-section. `top_n = 5` is roughly a decile-equivalent
and is fixed now.

## Configurations to be run

Exactly these two. No others.

```
--signal cef --start 2018-01-01 --end 2026-08-01 --top-n 5 --rebalance-every 21
--signal cef --start 2018-01-01 --end 2026-08-01 --top-n 5 --rebalance-every 63
```

The 63-day variant is declared because discount convergence is a slow process
and a monthly rebalance may churn out of positions before the thesis plays out.
Both are declared before any run and both count toward multiplicity.

Window is 2018-2026, not 2000-2026, because NAV history reaches back 10 years
only.

## Verdict rule

Unchanged, applied by `ghambla.walkforward.verdict`: strict majority of four
research windows at a Sharpe edge of at least +0.30 over SPY with drawdown no
worse, plus the holdout.

The multiplicity rule stands: this is the eleventh candidate, so **a pass does
not proceed to paper trading.** It must replicate on a disjoint set of CEFs not
used in this test before Gate 1.

## Honest prior

The placebo showed random portfolios reaching +0.06 at best. Ten candidates
have failed. The base rate for the eleventh is poor, and the small universe,
short window and survivorship bias all make a spurious pass more likely here
than in previous tests, not less.

Against that: this is the first candidate with a mechanism that is structural
rather than behavioural, and the first where the "fair value" is published
rather than estimated. That is a genuine difference, not a new flavour of the
same idea.

## What will be reported

Both configurations, pass or fail, with the survivorship caveat attached to any
result.

---

# Result

Run 2026-08-16. Both pre-registered configurations. **Both FAIL, 0/4 windows.**

| Rebalance | Research windows | Holdout edge |
|---|---|---|
| 21d | 0 of 4 | -0.65 |
| 63d | 0 of 4 | -0.40 |

Per-window Sharpe edge:

| Config | 2018-19 | 2019-21 | 2021-23 | 2023-24 | holdout 2024-26 |
|---|---|---|---|---|---|
| 21d | -0.29 | -0.00 | -0.09 | -1.30 | -0.65 |
| 63d | -0.04 | +0.09 | -0.67 | -1.29 | -0.40 |

Best figure across both: +0.09, against a +0.30 bar. Nine of ten windows
negative. The slower rebalance is mildly better early and no better late.

Candidate 11 fails, and the survivorship caveat recorded in the pre-registration
now cuts the other way: the universe is funds alive in 2026, which should have
*flattered* this result, and it still failed.
