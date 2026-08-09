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

*(empty — to be filled in after the runs, verbatim, including failures)*
