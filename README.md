# ghambla

An automated trading system for US equities and ETFs, executing through
Interactive Brokers.

**Status: Phase 1 complete. Gate 0 FAILED — not cleared for paper trading.**

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

## Running it

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                                    # 91 tests
.venv/bin/python -m ghambla.cli ingest              # ~45 min, 719 symbols
.venv/bin/python -m ghambla.cli backtest --start 2018-01-01 --end 2026-08-01
```

Ingest is deliberately paced so it does not hammer a free data endpoint. The
backtest over the full window takes about 13 minutes.

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

### Residual bias, still present

Coverage is 84.7%: 609 of 719 historical members could be priced. The missing
110 are disproportionately the acquired and delisted — AABA, ABMD, BCR, HAR,
LLTC, MJN, RAI, STJ — because data vendors stop serving history once a ticker
dies. Those names were never buyable by the backtest, so some survivorship
bias remains and the numbers above are still a little generous. Coverage is
recomputed on every ingest and printed under every result.

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
4. **Additional signals** — news/LLM, then fundamental/factor, each measured
   standalone before joining the ensemble.
5. **Allocator** — replace equal weighting.
6. **Live plumbing test** — NZ$100.

## Warning

Trading systems lose money. The evidence base is in section 1.1 of the design
doc: 97% of Brazilian futures traders who persisted past 300 days lost money,
and roughly 1% of day traders are consistently profitable over five years.
Nothing here is financial advice, and nothing here is expected to beat the
market until it has demonstrably done so out of sample.
