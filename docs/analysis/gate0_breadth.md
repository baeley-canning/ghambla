# Candidate 10: momentum at decile breadth — pre-registration

**Written and committed before the run.** No result at `top_n = 50` exists on
any window.

This is not a new signal. It is the claim that **every momentum result this
project has recorded so far tested a deliberately weakened version of the
published effect**, and that the weakening is in the portfolio construction
rather than the signal.

## The discrepancy

Momentum as published (Jegadeesh & Titman 1993, and the literature since) is
constructed as follows, against what this project has actually been running:

| | Published | This project |
|---|---|---|
| Universe | All NYSE + AMEX (~2,000 names) | S&P 500 only (~500) |
| Portfolio | Top **decile** — roughly 200 names | Top **10 names** |
| Direction | Long winners, **short** losers, dollar-neutral | Long-only |
| Formation | 6/6 most common; 12/3 strongest | 12-1 |
| Rebalance | Monthly | 21 days |

Formation and rebalance are close enough. Three things are not.

**Breadth is the largest tractable gap.** Top 10 of 500 is the top 2%. A decile
is the top 10%. Concentration at that level loads the portfolio with
idiosyncratic company risk that carries no expected return — it inflates the
denominator of the Sharpe ratio without touching the numerator.

**This matches the shape of what we already measured.** Momentum on 2018–2026
returned +239% against SPY's +178% — it beat the index on raw return and lost
on Sharpe (0.60 against 0.72), with a deeper drawdown. That is the exact
signature of a portfolio holding the right names too few at a time. If momentum
had no signal at all, the raw return should not have beaten the index either.

**Long-short is out of scope and stays out.** The published 1.31%/month figure
is winner-minus-loser. Long-only captures one leg and carries full market beta,
which is why it is being compared against SPY rather than against zero. The
design doc excludes shorting, that exclusion is not being revisited here, and
the NZ$100 account could not short in any case. This candidate does not test it.

## The hypothesis, fixed now

> Momentum's failure to clear the Sharpe gate is caused in material part by
> portfolio concentration, not by absence of signal. Widening from 10 names to
> a decile (50 of ~500) will raise the Sharpe ratio and reduce drawdown, with
> lower total return.

If the Sharpe edge does not improve at all, the concentration explanation is
wrong and momentum is simply absent on this data. That is a clean answer and
will be reported as such.

## Configurations to be run

Exactly these three. `top_n = 50` is the decile; 25 and 100 bracket it so the
result is a trend rather than a single point, and all three are declared here.

```
--signal momentum --start 2000-01-01 --end 2026-08-01 --top-n 25  --rebalance-every 21
--signal momentum --start 2000-01-01 --end 2026-08-01 --top-n 50  --rebalance-every 21
--signal momentum --start 2000-01-01 --end 2026-08-01 --top-n 100 --rebalance-every 21
```

No other parameter moves. Formation stays 12-1, rebalance stays 21 days,
weighting stays equal, no regime filter. If breadth is the explanation it must
show up with everything else held still.

## Verdict rule

Unchanged, and applied by `ghambla.walkforward.verdict`: a strict majority of
four research windows at a Sharpe edge of at least +0.30 over SPY with drawdown
no worse, plus the holdout.

The multiplicity rule from `gate0_candlestick_gap.md` carries over in full: this
is the tenth candidate on this data, so **a pass does not proceed to paper
trading**. It must first replicate unchanged on crypto daily bars.

## What will be reported

All three breadths, pass or fail, alongside the existing `top_n = 10` result so
the trend is visible. A monotonic improvement in Sharpe with breadth is the
prediction; anything else falsifies the hypothesis above and will be stated
plainly.
