# ghambla

An automated trading system for US equities and ETFs, executing through
Interactive Brokers.

**Status: Phases 1–5 built. Gate 0 FAILED on 26 years of data — no strategy is
cleared to trade, and the search is stopped.**

The machinery is complete and tested: point-in-time data, four signals, risk
gate, journal, reconciliation, broker adapters, daily cycle. What it does not
have is an edge. Every signal tested — alone and in combination — loses to SPY
on risk-adjusted terms, so running this against money — paper or real — would
be exercising the plumbing, not pursuing a strategy that works.

## What this is

A research and execution platform that reads market data, news, and
fundamentals, produces trade decisions from several independent signal
generators, and routes orders through IBKR — first against a simulated
account, and only later against a small live one.

The primary deliverable is not profit. It is an apparatus that can tell you
*honestly* whether a strategy has an edge. Most retail algo-trading projects
fail because the backtest quietly uses information that was not available at
the time, so the number it prints is fiction. This system is built so that
"no edge found" is a result it can actually report.

## Architecture

```
data → point-in-time store → signals → allocator → portfolio → RISK GATE → broker
                                                                    ↓
                                                    reconcile + journal (always)
```

| Module | Responsibility |
|---|---|
| `store/` | Point-in-time feature store. Every fact carries `knowable_at`; no read can return the future. |
| `sp500.py` | Dated index membership, so the universe is who was actually in the index that day. |
| `edgar.py` | SEC fundamentals keyed on filing date. |
| `signals/` | `momentum` (12-1), `fundamental` (value + quality), `news` (LLM classifier), `lowvol` (realised volatility). Pure functions over the store. |
| `allocator.py` | Averages percentile ranks, so no signal dominates by emitting bigger numbers. A lone signal is passed through uncentred. |
| `vol.py` | Realised volatility, shared by the low-vol signal and the allocator so they cannot drift. |
| `portfolio.py` | Scores → long-only targets, equal or inverse-vol weighted. |
| `risk.py` | The veto layer. Can only reduce or block. Fails closed. |
| `broker.py` | One interface: simulated, or IBKR. Sizing and risk live above it. |
| `reconcile.py` | Compares belief against the broker. Any break halts trading. |
| `journal.py` | Append-only JSONL of every decision and its reasoning. |
| `cycle.py` | One run of the whole thing. |
| `ibkr.py` | IBKR adapter. **Unit-tested only — never run against a real gateway.** |
| `marktomarket.py` | Marks the simulated book intraday. P/L arithmetic is pure and sign-pinned. |

### Mutation testing

Green tests are not evidence on their own — a delegated module can arrive with
tests that assert only what its author already believed. Sign- and
arithmetic-carrying code is therefore mutation-tested: flip the operator, and
confirm the suite fails. Four mutations have survived here and been closed:

| Survived mutation | Consequence had it shipped |
|---|---|
| Session P/L sign inverted | A losing session reported as a gain |
| Per-sample P/L sign inverted | Every logged row's P/L backwards |
| Sharpe sign inverted / annualisation dropped | Gate 0 decided on a number that could be backwards |
| Index-membership boundaries shifted a day | Universe silently gains or loses names at every index change |

## Running it

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                                    # 403 tests
.venv/bin/python -m ghambla.cli ingest              # ~45 min, 719 symbols
.venv/bin/python -m ghambla.cli backtest --start 2018-01-01 --end 2026-08-01
.venv/bin/python -m ghambla.cli evaluate --signal lowvol     # walk-forward Gate 0
```

`--signal` takes one name or several. Several are combined by rank average —
the same `RankAllocator` the live cycle uses — so a combination faces exactly
the same gate as a lone signal, with no separate easier path:

```bash
.venv/bin/python -m ghambla.cli evaluate --signal momentum fundamental
```

Ingest is deliberately paced so it does not hammer a free data endpoint. The
backtest over the full window takes about 13 minutes.

Run one decision cycle, and inspect what it decided:

```bash
.venv/bin/python -m ghambla.cli cycle --broker simulated
.venv/bin/python -m ghambla.cli cycle --broker simulated --halt   # kill switch
.venv/bin/python -m ghambla.cli journal --tail 10
```

`--broker ibkr` targets IB Gateway or TWS (paper Gateway 4002, live 4001;
paper TWS 7497, live 7496). `--live` only selects the live port — **the account
you log the gateway into is what decides whether the money is real.**

## Results so far

Momentum and value+quality as single-period backtests, both failing Gate 0, on
dated S&P 500 membership after IBKR Tiered commission and 5bp spread,
2018-01-01 to 2026-08-01:

| | Momentum (12-1) | Value+Quality | SPY |
|---|---|---|---|
| Total return | +239.49% | +119.80% | +177.94% |
| CAGR | +15.32% | +9.62% | +12.66% |
| Sharpe | 0.60 | 0.51 | 0.72 |
| Max drawdown | -36.31% | -36.01% | -34.10% |
| Sharpe edge | **-0.12** | **-0.21** | — |

Neither beats buying SPY and doing nothing. Both take more risk to get there.

## Walk-forward Gate 0

The single-period backtest above is the weaker test. `evaluate` re-runs each
candidate across four research windows plus an untouched holdout tail, and a
signal must clear the Sharpe edge in a *majority* of research windows and in
the holdout. Same universe, costs, and period as above.

| Signal | Weighting | Research windows passed | Holdout Sharpe edge | Verdict |
|---|---|---|---|---|
| `momentum` (12-1) | equal | 1 of 4 | +0.24, drawdown breach | **FAIL** |
| `lowvol` (252d realised) | equal | 1 of 4 | -0.23 | **FAIL** |
| `momentum + fundamental` | equal | 0 of 4 | +0.10, drawdown breach | **FAIL** |
| `momentum` (12-1) | inverse-vol | 1 of 4 | +0.23, drawdown breach | **FAIL** |

Re-baselined on **2000–2026** after extending the data, against a
[pre-registration](docs/analysis/gate0_matrix.md) committed before any result on
that window existed:

| Signal | Configuration | Research windows | Holdout | Verdict |
|---|---|---|---|---|
| `momentum` **(primary)** | regime filter + live parity | 1 of 4 | **-1.00** | **FAIL** |
| `momentum` | live parity | 0 of 4 | +0.05 | **FAIL** |
| `momentum` | baseline | 1 of 4 | +0.04 | **FAIL** |
| `lowvol` | regime filter + live parity | 2 of 4 | -0.71 | **FAIL** |

Six candidates have now failed a pre-registered gate. **The search is stopped**;
see [docs/analysis/gate0_matrix.md](docs/analysis/gate0_matrix.md) for the full
output and the reasoning.

Two findings worth keeping. The regime filter **did** fix the drawdown breaches
it was built for — three of five windows pass drawdown against zero of five
without it — but the Sharpe it cost exceeded the protection it bought, most
starkly in the holdout (+0.05 without, -1.00 with). And **nothing passes any
window after 2010**: three of four candidates pass 2000–2005 and none passes
anything since. Both anomalies were published decades ago. That shape is what
decay looks like from the inside.

Nothing is cleared to trade. Two details worth keeping in view:

Both single signals pass exactly one window out of four, and it is a
*different* window each time — momentum's is 2021-06..2023-02, low-vol's is
2018-01..2019-09. A single passing window is what curve-fitting looks like
from the inside, which is precisely why the majority rule exists.

Rank-averaging momentum with fundamental scored **worse than either alone**
(0 of 4). Combining weak signals diluted them rather than diversifying them.

### What inverse-volatility weighting was worth

Phase 5 replaced equal weighting with sizing proportional to `1 / vol`, on the
theory that equal weighting hands a violent name the same share as a calm one,
and that this was driving the repeated drawdown breaches.

| Window | Equal | Inverse-vol |
|---|---|---|
| 2018-01..2019-09 | -0.28, dd fail | -0.30, dd fail |
| 2019-09..2021-06 | -0.49, dd fail | -0.48, dd fail |
| 2021-06..2023-02 | **+0.44 pass** | **+0.46 pass** |
| 2023-02..2024-11 | -0.86, dd fail | -0.69, dd fail |
| holdout | +0.24, dd fail | +0.23, dd fail |

**It bought almost nothing, and it did not fix the thing it targeted.** Every
window that failed on drawdown still fails on drawdown. The single worst window
improved (-0.86 to -0.69) and the rest moved by hundredths.

Sizing by `1 / vol` equalises each position's *standalone* risk and does
nothing about *correlation*, so the obvious next suspect was that the ten
holdings simply fall together. That was a story, so it got measured rather
than believed — [docs/analysis/correlation_probe.py](docs/analysis/correlation_probe.py),
102 rebalances, against a control book of 10 names drawn at random from the
same universe on the same day.

| | Momentum top-10 | Random 10 (control) |
|---|---|---|
| Average pairwise correlation | **+0.394** | +0.282 |
| Diversification ratio | **1.534** | 1.769 |

The momentum book is more correlated than an arbitrary one — about 40% more,
and it gives up roughly 13% of the diversification a random book gets. So the
effect is real, and it is **far too small to explain the drawdowns.** A
diversification ratio of 1.53 is not a single factor bet; a book that was one
bet would sit near 1.00.

The correlation story was therefore mostly wrong, and the real answer is duller.
SPY's own maximum drawdown over this period is -34.10%; momentum's is -36.31%.
The strategy is not drawing down because its picks are unusually correlated
with each other — it is drawing down because it is a long-only equity book that
is always approximately 100% net long, so it eats the market's drawdown in full
whatever it holds. Clearing the drawdown half of Gate 0 needs lower net
exposure, a de-risking rule, or shorts. None of those exist here, and none of
them are position *sizing*.

Note also that equal weighting remains the default. The recorded results above
were produced under it, and a scheme that fails its own pre-registered test
does not become the default because it was newer.

### On adding more signals

Four candidates have now been measured against the same 2018–2026 data. Every
additional candidate raises the chance that a pass is multiple-comparisons
noise rather than an edge. The honest reading is that this dataset has been
queried enough that a future marginal pass should be treated with suspicion,
not celebration. A genuinely new dataset is worth more than a fifth signal.

## Current result

12-1 momentum, top 10 names, rebalanced every 21 days, 2018-01-01 to
2026-08-01, after IBKR Tiered commission and a 5bp spread. The universe is
dated S&P 500 membership — 718 tickers that were index members at some point
in the window, including those later acquired or delisted.

| Metric | Strategy | SPY |
|---|---|---|
| Total return | +239.49% | +177.94% |
| CAGR | +15.32% | +12.66% |
| Sharpe | 0.60 | 0.72 |
| Max drawdown | -36.31% | -34.10% |
| Trades | 1263 | 1 |

**Gate 0: FAIL.** Sharpe edge over SPY is **-0.12** against the +0.30
required, and drawdown is worse than the benchmark. The strategy does not
advance to paper trading.

It beats SPY on raw return and loses on risk-adjusted return. That is the
whole story: the extra 62 points of return were bought with extra risk, not
with skill.

### What survivorship bias was worth

The same strategy, run earlier against a hand-picked universe of 30 current
large caps:

| Metric | Biased universe | Dated membership | Change |
|---|---|---|---|
| Total return | +425.38% | +239.49% | -185.89pp |
| CAGR | +21.34% | +15.32% | -6.02pp |
| Sharpe | 0.99 | 0.60 | **-0.39** |
| Sharpe edge vs SPY | +0.27 | -0.12 | -0.39 |

**Survivorship bias was worth 0.39 of Sharpe — more than the entire apparent
edge.** The first run was not "nearly passing". It was measuring a universe
that knew in 2018 which companies would still be winning in 2026. Once the
backtest can only pick from names actually in the index at the time, and must
hold the ones that later collapsed, momentum has no risk-adjusted edge here.

### Residual bias, still present — and worse on the long window

Extending to 2000 made this materially worse, and the number is recorded here
before any performance result on the long window was read.

| Window | Requested | Priced | Coverage |
|---|---|---|---|
| 2016–2026 | 719 | 609 | **84.7%** |
| 2000–2026 | 1133 | 746 | **65.8%** |

387 of 1133 historical members cannot be priced — 202 returned
empty and 185 failed outright. Examples: AABA, AAMRQ, ABC, ABKFQ, ABMD, ABS, ACAS, ACKH.

They are disproportionately the acquired and delisted, because vendors stop
serving history once a ticker dies, and the longer the window the more dead
tickers it contains. Those names were never buyable by the backtest, so
survivorship bias remains and **every number on the 2000–2026 window is more
generous than reality by more than the 2016–2026 numbers were.** A third of
the universe being unpriceable is a real limitation, not a footnote.

Coverage is recomputed on every ingest and printed under every result.

### What not to do next

Tuning the lookback, the rebalance period, or the position count until Gate 0
passes is curve-fitting, and it is exactly what this harness exists to catch.
A real fix is a better signal, a genuinely different one, or accepting that
this strategy does not work.

## Design

[docs/superpowers/specs/2026-08-05-automated-trading-system-design.md](docs/superpowers/specs/2026-08-05-automated-trading-system-design.md)

Read sections 5 and 6 first — the graduation gates that decide when real
money gets involved, and why the NZ$100 live test verifies plumbing rather
than profitability.

## Key decisions

| Decision | Reason |
|---|---|
| Interactive Brokers | Open to NZ residents, mature API, free paper account mirroring the live API, free US stock/ETF data via Cboe One and IEX. |
| Plus500 rejected | Retail CFD platform has no API. Driving the UI gives no reliable fill confirmation, so the system could never reconcile its true position. |
| IBKR **Tiered** pricing, not Fixed | Fixed charges US$1.00 minimum per order — ~3.3% each way on a US$30 position. Tiered caps commission at 1% of trade value. |
| Python | `ib_async`, the quant libraries, and the LLM tooling all live there. |
| Paper before live | Same code path, swapped broker adapter. Real money unlocks only after numeric gates are cleared. |

## Roadmap

Phase 1 is the scope of the first implementation plan; later phases get
their own plans as each gate is cleared.

1. ~~**Honest measurement**~~ — done. Point-in-time feature store, backtest
   engine with the IBKR cost model, 12-1 momentum, evaluation harness.
2. **Decision machinery** — portfolio constructor, risk gate, journal.
3. **Paper trading** — IBKR paper adapter, reconciliation, daily scheduler.
4. ~~**Additional signals**~~ — done. news/LLM, fundamental/factor, low-vol,
   each measured standalone and in combination. All fail Gate 0.
5. ~~**Allocator**~~ — done. Inverse-volatility weighting built and measured;
   it fails Gate 0 and equal weighting remains the default.
6. **Live plumbing test** — NZ$100. Available only as a deliberate engineering
   exercise. Gate 0 has failed for every candidate, so no strategy is validated
   and none may be represented as such.

## Warning

Trading systems lose money. The evidence base is in section 1.1 of the design
doc: 97% of Brazilian futures traders who persisted past 300 days lost money,
and roughly 1% of day traders are consistently profitable over five years.
Nothing here is financial advice, and nothing here is expected to beat the
market until it has demonstrably done so out of sample.
