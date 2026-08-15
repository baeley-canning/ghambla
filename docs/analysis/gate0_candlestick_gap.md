# Candidates 8 and 9: candlestick patterns and gap reaction — pre-registration

**Written and committed before either signal existed.** No candlestick or gap
result has been computed on this data. `git log` shows this file landing before
`src/ghambla/signals/candles.py` and `src/ghambla/signals/gap.py`, which is the
only thing that makes the rest of this document worth anything.

## Why these two, and why now

Seven candidates have already failed a pre-registered gate. The base rate for
the eighth is not encouraging, and that has to be said before the numbers
arrive rather than after.

Both candidates are being tested because they were *requested*, and a request
is a legitimate reason to spend a test. They are not being tested because
anything in the previous seven results pointed here — nothing did.

## The multiplicity problem, stated up front

This is the eighth and ninth test on largely the same data. Each additional
test raises the chance that a pass is noise rather than signal. At the standard
gate (majority of research windows clearing a +0.30 Sharpe edge, plus the
holdout), running nine candidates makes at least one spurious pass materially
likely.

Therefore, fixed now:

> **A pass here does not proceed to paper trading.** It proceeds to a
> replication requirement: the same configuration, unchanged, must also clear
> the gate on crypto daily bars (a different asset class, already ingested and
> never used for equity candidate selection). Only a candidate passing both
> goes to Gate 1.

This is deliberately harder than what candidates 1–7 faced. That asymmetry is
the correct response to having already looked at this data seven times.

## Dataset

- Daily bars, 1996-08-08 .. 2026-08-07, 7,723 trading days, 4,395,740 bars.
- Universe: dated S&P 500 membership, as for every previous candidate.
- Window: **2000-01-01 .. 2026-08-01**, matching the candidates 6–7 baseline so
  results are comparable.
- Costs: IBKR Tiered commission, 5bp spread, next-open fills. Unchanged.

## Candidate 8: candlestick patterns

Classic single- and two-bar price-action patterns, scored cross-sectionally.
Pattern definitions are fixed here and may not be adjusted after seeing a
result:

| Pattern | Definition | Direction |
|---|---|---|
| Bullish engulfing | Today's body engulfs yesterday's, today up, yesterday down | long |
| Bearish engulfing | Today's body engulfs yesterday's, today down, yesterday up | avoid |
| Hammer | Lower shadow ≥ 2× body, upper shadow ≤ body, after a decline | long |
| Shooting star | Upper shadow ≥ 2× body, lower shadow ≤ body, after a rise | avoid |
| Marubozu (bull) | Body ≥ 90% of the high-low range, close at the top | long |
| Doji | Body ≤ 5% of the high-low range | neutral, no vote |

"Body" is `abs(close - open)`. "Range" is `high - low`. A bar with
`high == low` is skipped, not scored — it has no pattern and dividing by its
range is a zero-division.

Score is the sum of pattern votes over the last **3** trading days, +1 for each
long pattern and −1 for each avoid pattern, divided by 3. Lookback of 3 is
fixed now and will not be tuned.

Long-only, so only positive scores are eligible, as with every other signal.

## Candidate 9: gap reaction

Overnight gap: `(today_open / yesterday_close) - 1`.

Direction is pre-registered as **continuation**, not reversal, on the basis of
post-earnings-announcement drift — the documented tendency for prices to keep
moving in the direction of a surprise for weeks afterwards. Reversal is the
opposite hypothesis and would be a *tenth* candidate, not a re-run of this one.
If continuation fails, that is a result; flipping the sign and re-running is
p-hacking and is forbidden by this document.

- Signal value = the gap, averaged over gaps exceeding **1%** in absolute terms
  within the last **5** trading days. Gaps below 1% are noise and score zero.
- A symbol with no qualifying gap in the window abstains (confidence 0.0)
  rather than scoring zero, so it is excluded rather than ranked mid-pack.
- Both thresholds fixed now.

## Configurations to be run

Each candidate is run in exactly these two configurations. No others.

```
--signal candles  --start 2000-01-01 --end 2026-08-01 --top-n 10 --rebalance-every 21
--signal candles  --start 2000-01-01 --end 2026-08-01 --top-n 10 --rebalance-every 5
--signal gap      --start 2000-01-01 --end 2026-08-01 --top-n 10 --rebalance-every 21
--signal gap      --start 2000-01-01 --end 2026-08-01 --top-n 10 --rebalance-every 5
```

The 5-day rebalance is included because both patterns are short-horizon by
construction and a 21-day hold would discard the signal before it acts. It is
not a second bite at the same cherry; both are declared here, before any run,
and both count toward the multiplicity above.

## Verdict rule

Unchanged from every previous candidate, and applied by
`ghambla.walkforward.verdict`:

- 4 research windows plus an untouched holdout tail.
- A window passes on Sharpe edge ≥ **+0.30** over SPY **and** drawdown no worse
  than SPY.
- Gate 0 passes only on a strict majority of research windows **and** the
  holdout.
- Then, per the multiplicity rule above, replication on crypto before Gate 1.

## What will be reported

Every configuration run, pass or fail, in a single table. No configuration
declared here may be omitted from the report on the grounds that it did badly.

---

# Results

Run 2026-08-16. All four pre-registered configurations, none omitted.

| Signal | Rebalance | Research windows passed | Holdout Sharpe edge | Verdict |
|---|---|---|---|---|
| `candles` | 21d | 0 of 4 | -0.23 | **FAIL** |
| `candles` | 5d | 0 of 4 | -0.55 | **FAIL** |
| `gap` | 21d | 0 of 4 | -1.02 | **FAIL** |
| `gap` | 5d | 0 of 4 | -1.50 | **FAIL** |

Per-window Sharpe edge, research windows then holdout:

| Config | 2000-05 | 2005-10 | 2010-15 | 2015-21 | holdout 2021-26 |
|---|---|---|---|---|---|
| candles 21d | +0.05 | -0.14 | +0.00 | -0.34 | -0.23 |
| candles 5d | +0.05 | -0.24 | -0.35 | -0.08 | -0.55 |
| gap 21d | +0.09 | -0.05 | -1.10 | -0.74 | -1.02 |
| gap 5d | +0.15 | -0.35 | -0.91 | -1.31 | -1.50 |

Not one window out of twenty cleared +0.30. The best single figure anywhere in
the table is +0.15, half the bar, in the oldest window.

## What the numbers say

**Gap continuation is the worst candidate this project has tested.** Drawdown
fails in every window at both rebalance frequencies, and the holdout reaches
-1.50. That is not noise around zero; it is a strategy reliably doing the wrong
thing. Buying large caps that gapped up, after costs, destroys risk-adjusted
return.

**Trading more often makes both worse.** Every 5-day configuration is worse
than its 21-day counterpart in the holdout (-0.55 vs -0.23; -1.50 vs -1.02).
Five times the rebalances means five times the commission and spread against a
signal that was not paying for one round of costs, let alone five.

**The decay pattern repeats for the eighth and ninth time.** Both candidates
post their least-bad number in 2000-2005 and their worst in the two most recent
windows. Every signal this project has tested shows the same shape.

## What is not being done

The pre-registration fixed gap direction as continuation. The holdout is
-1.02 and -1.50, and inverting a signal that is reliably wrong is an obvious
temptation. **Gap-fade is candidate ten, not a re-run of candidate nine**, and
choosing to test it *because* continuation failed is selection on the outcome.
It is not being run here.

No configuration is omitted from the table above, including the two that
initially hit a 50-minute timeout and were re-run at a 4-hour limit. A timeout
is not a result and was not reported as one.
