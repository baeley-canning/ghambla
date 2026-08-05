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
.venv/bin/pytest                      # 58 tests
.venv/bin/python -m ghambla.cli ingest
.venv/bin/python -m ghambla.cli backtest --start 2018-01-01 --end 2026-08-01
```

## Current result

12-1 momentum, top 10 names, rebalanced every 21 days, 2018-01-01 to
2026-08-01, after IBKR Tiered commission and a 5bp spread:

| Metric | Strategy | SPY |
|---|---|---|
| Total return | +425.38% | +177.94% |
| CAGR | +21.34% | +12.66% |
| Sharpe | 0.99 | 0.72 |
| Max drawdown | -30.64% | -34.10% |
| Trades | 1109 | 1 |

**Gate 0: FAIL.** The Sharpe edge over SPY is +0.27, short of the +0.30
required. The strategy does not advance to paper trading.

That headline return looks impressive and should be distrusted. The starter
universe is today's large caps, so the backtest implicitly knew in 2018 which
companies would still be winners in 2026 — the numbers above are inflated by
survivorship bias and *still* fail the gate. Fixing the bias will lower them.

The correct next move is a better signal or an unbiased universe, not looser
thresholds. Tuning parameters until the gate passes is curve-fitting, which is
precisely what this harness exists to catch.

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
