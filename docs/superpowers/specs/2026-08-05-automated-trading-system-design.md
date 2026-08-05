# Automated Trading System — Design

**Date:** 2026-08-05
**Status:** Draft for review
**Working name:** `trader`

---

## 1. What we are actually building

A research and execution platform that ingests market data, news, and fundamentals for US equities and ETFs, produces trade decisions from several independent signal generators, and routes orders through Interactive Brokers — first against a simulated account, and only later against a small live account.

The system's most important property is **not** that it makes money. It is that it can tell you *honestly whether it makes money*. Almost every retail algo-trading project fails not because the strategy is bad but because the measurement is dishonest — the backtest quietly uses information that was not available at the time, and the number it prints is fiction. This design treats the measurement apparatus as the primary deliverable and the strategy as a plug-in.

### 1.1 The premise, stated honestly

The original brief said the system "will outperform most professional traders." That is a hypothesis to be tested, not a requirement to be implemented. The evidence base is worth stating plainly before we spend months on this:

- A study of Brazilian equity index futures traders who persisted beyond 300 trading days found 97% lost money; among the 3% who profited, the median daily gain was about US$10.
- FINRA data for 2020 showed 72% of day traders finished the year with losses.
- Barber & Odean's 66,465-account study found the most active retail traders returned 11.4% annually against a market return of 17.9% — the trading itself was the cost.
- Roughly 1% of day traders are consistently profitable over a five-year horizon.

None of this means the project is pointless. It means the correct goal is: **build an apparatus that can detect a real edge if one exists, and — much more likely — tell you clearly and early that one does not.** A system that credibly reports "no edge found" after six months has done its job and saved you money. A system that reports a 300% backtest return has almost certainly lied to you.

It is worth contrasting this with a game where an edge genuinely is provable. Card counting in blackjack works because the advantage can be derived in advance, is known to be small, and survives only under strict bankroll discipline. Markets offer no equivalent proof — nobody can hand you the edge before you trade. So the discipline has to be tighter, not looser, and the entire burden of proof sits with the strategy.

---

## 2. Integration path decision

Three paths were considered. Only one is viable.

### Rejected: Plus500

Plus500's retail CFD platform provides **no API and no automated-trading support**. Their institutional futures arm (Plus500 Futures Technologies / T4) does expose FIX and .NET APIs, but that is a different entity and a different product — a US-regulated futures commission merchant, not the retail CFD account. Automating the retail platform would require driving the UI, which:

- violates their terms of service, exposing you to account termination and frozen funds;
- gives no reliable order acknowledgement or fill confirmation, so the system can never know its true position;
- breaks silently on every UI change;
- puts you in the leveraged CFD segment, where brokers' own published disclosures show 70–80% of retail accounts lose money.

Screen-reading is rejected for the same reasons plus one more: a trading system that cannot reconcile its believed state against the broker's actual state is not a trading system, it is a random order generator with a nice dashboard.

### Rejected for now: Tiger Brokers NZ

FMA-licensed in New Zealand, has an OpenAPI, cheap at US$1.99 per US trade. Reasonable fallback, but the API and its documentation are less mature than IBKR's, the historical data access is weaker, and the flat per-trade fee is punishing at the position sizes in our live test.

### Selected: Interactive Brokers

- Open to NZ residents (IBKR LLC, Pro plan).
- Mature, well-documented APIs: TWS API via IB Gateway, plus a REST Client Portal / Web API.
- **Free paper-trading account that mirrors the live API surface**, which is what makes the gated-graduation approach possible at all.
- Free real-time US stock and ETF data from Cboe One and IEX, so the research and paper phases cost nothing in data fees. Consolidated NYSE/Nasdaq feeds are a few dollars a month if we later need them; a daily-bar strategy does not.
- Fractional US shares, which the live test requires.
- Deep historical data for backtesting.

**Pricing choice: Tiered, not Fixed.** This is not a preference, it is a hard requirement of the live test — see §6.

---

## 3. Architecture

One decision path, three execution backends. The same code that produces a backtest decision produces a paper decision and a live decision; only the broker adapter is swapped. Any logic that exists in only one of those paths is a bug waiting to happen.

```
                        ┌──────────────────────────────────┐
  Market data ─────────►│                                  │
  News / filings ──────►│   Point-in-time Feature Store    │
  Fundamentals ────────►│   (everything stamped with       │
                        │    ingest time, not just         │
                        │    publish/period time)          │
                        └────────────────┬─────────────────┘
                                         │  as_of(T)
                        ┌────────────────▼─────────────────┐
                        │        Signal Generators         │
                        │  technical │ news+LLM │ factor   │
                        └────────────────┬─────────────────┘
                                         │ scores
                        ┌────────────────▼─────────────────┐
                        │           Allocator              │
                        └────────────────┬─────────────────┘
                        ┌────────────────▼─────────────────┐
                        │      Portfolio Constructor       │
                        │      (scores → target sizes)     │
                        └────────────────┬─────────────────┘
                        ┌────────────────▼─────────────────┐
                        │           RISK GATE              │
                        │      can veto anything           │
                        └────────────────┬─────────────────┘
                        ┌────────────────▼─────────────────┐
                        │       Execution Adapter          │
                        │  Backtest │ IBKR Paper │ IBKR Live│
                        └────────────────┬─────────────────┘
                        ┌────────────────▼─────────────────┐
                        │  Reconciliation  +  Journal      │
                        └──────────────────────────────────┘
```

### 3.1 Components

**Feature Store (point-in-time).** Local storage (SQLite for metadata, Parquet for bars) of daily OHLCV, corporate actions, quarterly fundamentals, and news items. Every record carries the timestamp at which the information *became knowable*, which for fundamentals is the report date and not the period end, and for news is the publish timestamp. Universe membership is stored as dated snapshots so backtests do not silently trade companies that had not yet listed or had already been delisted. The single query interface is `as_of(T)`, which is physically incapable of returning a record stamped later than `T`.

*What it does:* answers "what was knowable at time T". *How you use it:* one method. *What it depends on:* nothing but the data files.

**Signal Generators.** A plug-in interface: `score(as_of, universe) -> {symbol: Score(value, confidence, rationale)}`. Pure functions over the feature store — no network calls, no clock reads, no state. This purity is what makes them independently testable and backtest-reproducible.

- *Technical* — momentum, mean reversion, volatility regime, cross-sectional ranking.
- *News + LLM* — an LLM classifies headlines and filings for materiality and direction. Responses cached by content hash so a backtest is deterministic and does not re-bill the API on every run.
- *Fundamental / factor* — value, quality, earnings-revision ranking, rebalanced weekly or monthly.

**Allocator.** Combines signal scores into one ranking. Starts as fixed equal weight. The LLM-weighted-by-regime version is a later drop-in replacement behind the same interface. Whichever allocator ran, and with what weights, is recorded on every decision.

**Portfolio Constructor.** Converts the combined ranking into target positions using volatility-scaled sizing with a cap on any single name, and a maximum position count. Outputs *target state*, not orders; the diff against current state produces orders.

**Risk Gate.** The veto layer, and the most important code in the repository. Hard, non-negotiable limits: maximum position size as a share of equity, maximum gross exposure, daily loss limit, peak-to-trough drawdown halt, and a refusal to trade at all if data is stale, if reconciliation last failed, or if the broker connection has flapped. It can only ever reduce or block, never increase. It is also the manual kill switch.

**Execution Adapters.**
- `BacktestBroker` — models IBKR Tiered commission *including the 1%-of-trade-value cap*, bid-ask spread, and slippage. Fills at the **next** bar's open, never at the close of the bar that generated the signal. This one rule eliminates the most common source of fake backtest returns.
- `IBKRPaperBroker` — IB Gateway against the paper account.
- `IBKRLiveBroker` — identical code, live credentials, plus an explicit arming step that cannot be set from a config file alone.

**Reconciliation.** After every cycle, compare believed positions and cash against what IBKR reports. Any mismatch halts trading and alerts. Silent state drift is the failure mode that turns a small bug into a large loss.

**Journal.** Append-only record of every decision: as-of time, hash of inputs, each signal's score and rationale, allocator weights, target versus actual positions, orders, fills, and the reason for any veto. This is what lets you answer "why did it buy that" three weeks later, and it is what makes the paper-versus-backtest comparison in §5 possible.

**Evaluation Harness.** Walk-forward analysis, a genuinely untouched out-of-sample holdout, benchmark comparison against SPY buy-and-hold after costs, and computation of the graduation metrics.

### 3.2 Language and stack

Python: `ib_async`/`ib_insync` for IBKR, pandas or polars for the data layer, and the entire quantitative and LLM ecosystem are Python-native. Choosing anything else would mean reimplementing tooling that already exists and is well tested.

The repository holds nothing but this project, so implementation lives at the repository root as a standard Python package rather than in a subdirectory.

---

## 4. Error handling

The default response to anything unexpected is **stop trading and tell the human** — never "retry and hope". Specifically:

- **Stale or missing data** — the risk gate blocks all new orders. Existing positions are held, not liquidated, because liquidating on bad data is itself a trade made on bad data.
- **Broker disconnect** — halt, attempt reconnect with backoff, and on reconnect run reconciliation *before* any order. Never assume in-flight orders did not fill.
- **Partial fills** — the position is whatever the broker says it is; the constructor re-plans from actual state on the next cycle rather than chasing the remainder.
- **Order rejection** — logged with the broker's reason, no automatic resubmission.
- **LLM failure or timeout** — that signal returns "no opinion" with zero confidence. It never blocks the cycle and never defaults to a directional view.
- **Reconciliation break** — hard halt requiring manual clearance.

---

## 5. Graduation gates

Progression is one-directional and each gate has a number attached before the work starts, so the result cannot be rationalised after the fact.

**Gate 0 → 1 — the backtest is trustworthy.** On out-of-sample walk-forward data, after modelled costs, the strategy achieves a Sharpe ratio at least 0.3 higher than SPY buy-and-hold over the same period, with maximum drawdown no worse than SPY's. Point-in-time tests pass. A deliberately injected lookahead bug is caught by the test suite.

**Gate 1 → 2 — paper trading.** A minimum of 60 trading days and 30 trades on the IBKR paper account. The pass condition is *not* "paper made money" — it is that **paper results track what the backtest predicted for those same dates**. Concretely: run the backtest over the identical date range and universe, and require the correlation of daily returns between backtest and paper to be at least 0.90, with the difference in cumulative return no greater than 3 percentage points. Divergence beyond that means the backtest was using information the live system does not have, and the correct response is to fix the backtest, not to trade anyway.

**Gate 2 → 3 — live plumbing test.** Zero unresolved reconciliation breaks across the entire paper period, kill switch tested under load, and the full order lifecycle exercised including partial fills, rejections, and a trading halt.

---

## 6. The NZ$100 live test: what it can and cannot prove

NZ$100 is roughly US$60. This constrains the design in ways worth being explicit about.

**Tiered pricing is mandatory.** IBKR Fixed pricing charges a minimum of US$1.00 per order. On a US$30 position that is 3.3% each way — about 6.6% round-trip, which no strategy survives. Tiered charges US$0.0035 per share with a US$0.35 minimum **capped at 1% of trade value**, so the same US$30 trade costs US$0.30. Round-trip friction lands near 2–2.5% including spread and regulatory fees.

**It must be a cash account, and the strategy must hold overnight.** The US pattern-day-trader rule requires US$25,000 of equity for frequent day trading in a margin account. At this size the account must be cash, which also means T+1 settlement limits how quickly funds can be recycled. The strategy therefore has to be multi-day swing or slower — which suits the fundamental and news signals anyway.

**What the test proves:** that orders reach the exchange, that fills come back and are parsed correctly, that positions and cash reconcile against a real broker, that the risk gate fires against real money, and that fractional-share sizing works.

**What the test cannot prove:** anything about profitability. With ~2% round-trip costs, US$60 of capital, and a handful of trades, the outcome is statistically indistinguishable from noise in either direction. Making money on this test is not evidence the strategy works, and losing money is not evidence it does not. Budget for roughly 3–8 trades and treat the entire NZ$100 as the cost of verifying the wiring.

---

## 7. Build sequence

Sequencing matters more than usual here, because building all four signal types simultaneously is the single most likely way this project dies. Each signal is measured on its own against the same harness before it is allowed into the ensemble.

This document is deliberately larger than one implementation plan. **Phase 1 is the scope of the first plan**; each later phase gets its own plan written when the preceding gate is cleared, so that later phases can be informed by what earlier ones actually revealed.

**Phase 1 — Honest measurement.** Feature store with point-in-time guarantees, backtest engine with the cost model, one deliberately simple signal (12-1 momentum), evaluation harness. *Deliverable: a backtest you have reason to trust.* This phase is the project. Everything after it is comparatively easy.

**Phase 2 — Decision machinery.** Portfolio constructor, risk gate, journal.

**Phase 3 — Paper trading.** IBKR paper adapter, reconciliation, scheduler running the daily cycle unattended.

**Phase 4 — Additional signals.** News + LLM, then fundamental/factor. Each evaluated standalone before joining the ensemble.

**Phase 5 — Allocator.** Replace equal weighting once there is more than one signal with demonstrated standalone value.

**Phase 6 — Live plumbing test.** Per §6.

---

## 8. Testing strategy

Test-driven throughout, with four categories that carry most of the weight:

1. **Point-in-time correctness.** Property test: for any feature computed as of `T`, assert no input record has an ingest timestamp later than `T`. Include a deliberately planted lookahead bug in the test suite and assert it is caught.
2. **Cost model.** Unit tests pinning IBKR Tiered commission, including the 1% cap at small trade values — the case the live test depends on.
3. **Risk gate.** Every limit tested for correct veto, and tested to confirm it can never increase exposure.
4. **Reconciliation.** Inject artificial position and cash drift; assert the system halts.

Plus integration tests running a full cycle against the IBKR paper account.

---

## 9. Regulatory and tax notes (New Zealand)

Not legal or tax advice; flagged so it is not discovered late.

- Trading your own money through your own account does not require an FMA licence. Managing money for others, or offering this as a service, would likely require a DIMS licence — a hard boundary this project does not approach.
- IRD generally treats gains as taxable income where assets are acquired with the intention of resale, which systematic trading plainly is. Assume trading profits are taxable income, and keep the journal in a form that supports filing.
- Foreign Investment Fund rules apply above NZ$50,000 of cost in offshore shares. Well outside the scope of this project, but relevant if it were ever scaled.
- Professional advice is warranted before any deployment materially larger than the NZ$100 test.

---

## 10. Explicitly out of scope

Intraday and high-frequency trading; leverage, margin, and short selling; options and futures; CFDs and any Plus500 integration; managing anyone else's money; a mobile app; a real-time web dashboard (the journal plus a static daily report covers Phase 1–3 needs).
