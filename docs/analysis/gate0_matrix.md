# Gate 0 re-baseline on the extended window — pre-registration

**Written and committed before any result on this window was seen.** Commit
`fc335ab` or earlier is the last commit that could have been informed by a
2000–2026 number, and none existed at that point: the re-ingest was still
running.

The point of writing this first is that it cannot be edited afterwards without
showing up in `git log`. Five candidates have already been tested on 2018–2026.
Every further test on the same data raises the chance a pass is noise. The
extended window is a genuinely new sample and it gets spent once.

## Dataset

- Bars: daily, `--range 30y`, from 1996-09-01. Universe start 2000-01-01.
- **Coverage will be materially worse than the 84.7% recorded for 2016–2026.**
  The first extended ingest reported 67.8% (768 priced of 1133). The number
  from the corrected ingest goes into `README.md` *before* any performance
  result is read, so the caveat cannot be tuned to suit the outcome.
- **Fundamentals begin 2009-04-15.** SEC XBRL structured data does not exist
  earlier. This is a hard limit of the source, not a gap to be filled.

## Period split, fixed now

| Candidate family | Period | Why |
|---|---|---|
| momentum, lowvol | 2000-01-01 .. 2026-08-01 | bars only; full window available |
| anything using `fundamental` | 2009-04-15 .. 2026-08-01 | XBRL floor |

A fundamental result over 2009+ is **not** comparable to a momentum result over
2000+. They will be reported in separate tables and never in one ranking.

## Primary candidate — the one that decides Gate 0

```
--signal momentum --regime-filter --live-parity
--start 2000-01-01 --end 2026-08-01 --top-n 10 --rebalance-every 21
```

Chosen because both additions follow from measurement rather than fitting:

- The correlation probe (102 rebalances, random control) found the momentum
  book only modestly more correlated than an arbitrary one — +0.394 against
  +0.282, diversification ratio 1.53 against 1.77. Far too small to explain
  30%+ drawdowns. SPY's own max drawdown is -34.10% against momentum's -36.31%.
  The book draws down because it is ~100% net long, so the remedy has to be net
  exposure.
- The trend filter is the standard tactical-allocation rule at its standard
  200-day parameterisation (Faber 2007), not a threshold picked from this data.
- `--live-parity` because Gate 0 must measure the configuration that would
  actually trade: risk gate on, cash buffer on.

## Secondary candidates — reported, never decisive

1. `momentum --live-parity` (no regime filter) — isolates what the filter is worth
2. `momentum` (no filter, no parity) — reproduces the 2018–2026 baseline on new data
3. `lowvol --regime-filter --live-parity`
4. `momentum fundamental --regime-filter --live-parity`, **2009+ only**

## Decision rule, fixed in advance

- The **primary** candidate alone decides Gate 0.
- A secondary passing while the primary fails is a multiple-comparisons
  artefact and does **not** advance to paper trading.
- Each candidate is run **once**. No rerun with adjusted parameters. If a run
  errors for a technical reason, the fix is committed and the run repeated —
  and the fact that it was repeated is recorded here.
- Pass condition is unchanged from the design doc: Sharpe edge ≥ **+0.30** over
  SPY in a **majority** of research windows **and** in the holdout, with maximum
  drawdown no worse than SPY's.

## If the primary fails

Stop. Six candidates will have failed a pre-registered gate across 26 years
including the dot-com unwind, the GFC and the 2009 momentum crash. That is a
result, and the honest response is to record it — not to search for a seventh.

The NZ$100 plumbing test may still be run deliberately as an engineering
exercise, but it must be labelled as such in `README.md`, and no strategy may
be represented as validated.

## Results

Run once each on 2000-01-01..2026-08-01, top 10, rebalance 21d, against a
snapshot of the store taken after the corrected 30y ingest. Pasted verbatim.

### PRIMARY — momentum, equal, --regime-filter --live-parity

```
Signal: momentum_12_1
Period: 2000-01-01 .. 2026-08-01  (4 research windows + 1 holdout)

Window                   Type      Sharpe edge Drawdown ok  Verdict
-------------------------------------------------------------------
2000-01-01..2005-04-24   research        +0.65         YES  PASS
2005-04-25..2010-08-18   research        +0.24         YES  FAIL
2010-08-19..2015-12-11   research        -0.22          NO  FAIL
2015-12-12..2021-04-06   research        -0.14         YES  FAIL
2021-04-07..2026-08-01   holdout         -1.00          NO  FAIL

Gate 0 (walk-forward): FAIL (1/4 research windows passed (need > 50%); holdout failed)
Do not proceed to paper trading.
```

### Secondary 1 — momentum, --live-parity (no regime filter)

```
Signal: momentum_12_1
Period: 2000-01-01 .. 2026-08-01  (4 research windows + 1 holdout)

Window                   Type      Sharpe edge Drawdown ok  Verdict
-------------------------------------------------------------------
2000-01-01..2005-04-24   research        -0.03          NO  FAIL
2005-04-25..2010-08-18   research        +0.05          NO  FAIL
2010-08-19..2015-12-11   research        -0.21          NO  FAIL
2015-12-12..2021-04-06   research        -0.28          NO  FAIL
2021-04-07..2026-08-01   holdout         +0.05          NO  FAIL

Gate 0 (walk-forward): FAIL (0/4 research windows passed (need > 50%); holdout failed)
Do not proceed to paper trading.
```

### Secondary 2 — momentum, no filter, no parity (baseline)

```
Signal: momentum_12_1
Period: 2000-01-01 .. 2026-08-01  (4 research windows + 1 holdout)

Window                   Type      Sharpe edge Drawdown ok  Verdict
-------------------------------------------------------------------
2000-01-01..2005-04-24   research        +0.44         YES  PASS
2005-04-25..2010-08-18   research        -0.08          NO  FAIL
2010-08-19..2015-12-11   research        -0.22          NO  FAIL
2015-12-12..2021-04-06   research        -0.28          NO  FAIL
2021-04-07..2026-08-01   holdout         +0.04          NO  FAIL

Gate 0 (walk-forward): FAIL (1/4 research windows passed (need > 50%); holdout failed)
Do not proceed to paper trading.
```

### Secondary 3 — lowvol, --regime-filter --live-parity

```
Signal: low_vol
Period: 2000-01-01 .. 2026-08-01  (4 research windows + 1 holdout)

Window                   Type      Sharpe edge Drawdown ok  Verdict
-------------------------------------------------------------------
2000-01-01..2005-04-24   research        +0.68         YES  PASS
2005-04-25..2010-08-18   research        +0.41         YES  PASS
2010-08-19..2015-12-11   research        -0.03         YES  FAIL
2015-12-12..2021-04-06   research        +0.08         YES  FAIL
2021-04-07..2026-08-01   holdout         -0.71         YES  FAIL

Gate 0 (walk-forward): FAIL (2/4 research windows passed (need > 50%); holdout failed)
Do not proceed to paper trading.
```

## Verdict

**Gate 0: FAIL.** The primary candidate passed 1 of 4 research windows and failed
the holdout at -1.00. Per the decision rule fixed above, the primary alone
decides, so nothing advances to paper trading.

Secondary 3 (lowvol) came closest at 2 of 4 — and 2 of 4 is not a majority, the
rule being *strictly more than half*. Its holdout was -0.71. It does not rescue
the result and, being a secondary, could not have.

### What the regime filter actually did

Compare the primary against Secondary 1, which differs only in the filter:

| Window | Primary (filter) | Secondary 1 (no filter) |
|---|---|---|
| 2000-01..2005-04 | **+0.65, dd ok** | -0.03, dd fail |
| 2005-04..2010-08 | +0.24, dd ok | +0.05, dd fail |
| 2010-08..2015-12 | -0.22, dd fail | -0.21, dd fail |
| 2015-12..2021-04 | -0.14, dd ok | -0.28, dd fail |
| holdout 2021-04..2026-08 | **-1.00**, dd fail | +0.05, dd fail |

**The filter did the job it was built for.** Drawdown went from failing every
window to passing three of five. The diagnosis — that the book takes the
market's full drawdown because it is always ~100% net long — was correct, and
the remedy addressed it.

It still fails, because fixing drawdown cost more Sharpe than it bought. The
holdout is the clearest case: +0.05 without the filter, **-1.00** with it. A
200-day moving average exits after a decline is already underway and re-enters
after a recovery is already underway, which is close to worst-case behaviour in
the sharp V-shaped recoveries of 2020 and 2022. It bought protection in the
slow 2000-2002 bear market and paid for it many times over since.

### The pattern across every candidate

The 2000-01..2005-04 window passes for three of four candidates. **Nothing
passes any window after 2010.** Both anomalies under test — cross-sectional
momentum and low volatility — were published decades ago and have been widely
traded since. A result that lives entirely in the first third of the sample and
disappears from the last two thirds is what decay looks like from the inside.



---

## Addendum — candidate seven: short-term reversal

Added after the four above, as a genuinely different anomaly family rather than
another spin on momentum. Buy yesterday's biggest losers, daily rebalance,
`--live-parity`.

```
Signal: reversal
Period: 2000-01-01 .. 2026-08-01  (4 research windows + 1 holdout)

Window                   Type      Sharpe edge Drawdown ok  Verdict
-------------------------------------------------------------------
2000-01-01..2005-04-24   research        +0.73         YES  PASS
2005-04-25..2010-08-18   research        +0.29         YES  FAIL
2010-08-19..2015-12-11   research        -0.11          NO  FAIL
2015-12-12..2021-04-06   research        -0.49          NO  FAIL
2021-04-07..2026-08-01   holdout         -0.86          NO  FAIL

Gate 0 (walk-forward): FAIL (1/4 research windows passed (need > 50%); holdout failed)
Do not proceed to paper trading.
```

**FAIL.** 1 of 4 research windows, holdout -0.86.

### Cost sensitivity — the reason it was worth testing at all

A single-year backtest (2010, daily rebalance, top 10) passed Gate 0 at +58.56%
against SPY's +19.82%. That number is entirely an artefact of the modelled
spread:

| Spread | Return | Sharpe | Edge vs SPY (0.86) |
|---|---|---|---|
| 5bp | +58.56% | 1.40 | +0.54 |
| 25bp | +28.71% | 0.85 | **-0.01** |
| 50bp | -0.98% | 0.15 | -0.71 |
| 100bp | -41.88% | -1.26 | -2.12 |

At ~3,000 trades a year, one basis point of cost is worth roughly 1.5
percentage points of annual return. Interpolating, Gate 0's +0.30 edge survives
only below about **14bp all-in round trip** — for a basket of yesterday's
biggest losers, bought at the next open, at 10% of equity per name. That is the
textbook profile of an anomaly that is real gross and eaten entirely by
execution.

## Conclusion after seven candidates

| Candidate | Best window | Anything after 2010? |
|---|---|---|
| momentum (12-1) | 2000-2005 | no |
| momentum + fundamental | none | no |
| lowvol | 2000-2005, 2005-2010 | no |
| inverse-vol weighting | 2021-2023 only | no |
| momentum + regime filter | 2000-2005 | no |
| reversal | 2000-2005 | no |

**Nothing passes any window after 2010.** Seven candidates spanning
cross-sectional momentum, low volatility, value/quality, short-term reversal,
two weighting schemes and a trend filter. Every one shows an edge in the first
third of the sample and nothing in the last two thirds.

These anomalies were published decades ago and are traded by everyone. The
consistent finding is not that this implementation is bad — the harness detected
a real effect in 2000-2010 in six of seven cases, which is evidence it works.
The finding is that the effects are gone from US large caps at daily frequency.

**The strategy search is closed.** Further candidates on this dataset are
p-hacking. What would change the answer is a different market, a different
frequency with the execution data to price it honestly, or a genuinely
non-public signal — not an eighth variation.
