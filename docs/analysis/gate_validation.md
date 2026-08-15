# Validating the gate itself

Ten candidates have failed Gate 0. Before that means anything, the gate has to
be shown to be a real test. Two failure modes had to be ruled out, and they
pull in opposite directions:

- **Too loose:** the gate passes things at random, so a pass would be luck.
- **Too tight:** the gate rejects everything, so a failure says nothing about
  the signal and ten failures are ten non-results.

A single experiment cannot rule out both. It takes two.

## Test 1 — placebo: does the gate pass noise?

30 portfolios chosen by pure noise, through the identical `run_walk_forward`
and `verdict` every real candidate faces. `RandomSignal` never reads the store;
a test injects a store that raises on any attribute access, because a placebo
that peeked at prices would not be a placebo.

```
Placebo trials: 30
Gate 0 passed: 0 (0.0%)
Median holdout Sharpe edge: -0.33
Best holdout Sharpe edge: +0.06

Research windows passed:  0: 14   1: 13   2: 3   3: 0   4: 0
```

**Nothing random ever cleared 3 of 4 windows**, let alone the holdout. The gate
does not hand out passes.

That alone proves only that false positives are rare. A gate that rejected
everything would produce this identical table.

## Test 2 — power: can the gate detect an edge that is definitely there?

`OracleSignal` blends a symbol's **future** return with noise at a tunable
strength. Strength 0.0 is pure noise; 1.0 is perfect foresight. It deliberately
breaks the point-in-time guarantee through one commented helper and says so in
its own docstring — it exists to measure the instrument and must never be run
as a candidate.

| Strength | Research windows | Holdout edge | Gate |
|---|---|---|---|
| 0.00 | 0 of 4 | -0.20 | fail |
| 0.05 | 1 of 4 | +0.28 | fail |
| **0.10** | **3 of 4** | **+0.67** | **PASS** |
| 0.25 | 3 of 4 | +2.20 | PASS |
| 0.50 | 3 of 4 | +3.47 | PASS |
| 1.00 | 3 of 4 | +4.82 | PASS |

Monotonic in strength, failing at noise and passing from 0.10 upward. The
detection floor sits between 0.05 and 0.10, and 0.05 lands at +0.28 against a
+0.30 bar — just under, which is the behaviour of a threshold doing its job
rather than one set arbitrarily.

## Verdict on the gate

**The gate is a valid test.** It rejects noise (0 of 30) and detects a genuine
edge from about 10% strength upward. It is neither loose nor broken.

Therefore the ten candidate failures mean what they appear to mean.

## Where the tested signals sit

Holdout Sharpe edge, real candidates against both calibrations:

| | Holdout edge |
|---|---|
| Oracle, strength 1.00 | +4.82 |
| Oracle, strength 0.10 (detection floor) | +0.67 |
| Oracle, strength 0.05 (just below the bar) | +0.28 |
| Best of 30 random portfolios | +0.06 |
| **Momentum (best real candidate)** | **-0.12** |
| Median random portfolio | -0.33 |
| **Candlesticks** | **-0.23** |
| **Gap continuation** | **-1.02** |

No tested signal reaches even the *random* best case, let alone the detection
floor. They are not near-misses on a demanding bar. They sit inside the noise
distribution — and gap sits below all 30 random portfolios, which is its own
kind of finding: buying large caps that gapped up is a real effect pointing the
wrong way.

## Limitations, stated plainly

**The oracle is an idealised edge.** It is a clean cross-sectional ranking
blended with noise. A real signal has different structure — concentrated in
certain regimes, correlated with sectors, weaker in the tails — so 0.10 is a
calibration, not a precise threshold. A real effect of comparable economic size
but messier structure could still fail.

**Even perfect foresight only passes 3 of 4 research windows.** Strength 1.00
fails a window, on drawdown. That is a demanding gate, and worth knowing: it
means the drawdown criterion can reject a strategy that is right about
everything. It still passes overall, so the gate is not impossible — but it is
strict, and a marginal real effect would be rejected.

**30 trials bounds the false-pass rate loosely.** Zero passes in 30 is
consistent with a true rate anywhere below roughly 10%. It is not evidence of
exactly zero.

## What this closes

The project's stated primary deliverable was an apparatus that could honestly
report "no edge found" rather than printing a flattering number. That claim now
has evidence behind it in both directions rather than only the pessimistic one.

The apparatus works. The answer it gives is no.
