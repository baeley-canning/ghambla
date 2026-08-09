# ghambla Completion Plan — through to the NZ$100 live plumbing test

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take ghambla from "machinery built, Gate 0 failed on a thin dataset" to a system that has either cleared or definitively failed all three graduation gates, ending at the NZ$100 live plumbing test.

**Architecture:** The design doc's central rule is *"One decision path, three execution backends. Any logic that exists in only one of those paths is a bug waiting to happen."* Two such divergences have already been found and fixed (signal scoring, the risk gate). Phase A closes the last two. Everything after that is measurement and operations, not new strategy.

**Tech Stack:** Python 3.12, stdlib + `ib_async`, SQLite feature store, pytest.

## Global Constraints

- **Gate 0** (design §5): out-of-sample walk-forward, Sharpe edge ≥ **+0.30** over SPY, max drawdown **no worse than SPY**, point-in-time tests pass, injected lookahead bug caught.
- **Gate 1** (design §5): ≥ **60 trading days** and ≥ **30 trades** on IBKR paper; daily-return correlation vs backtest ≥ **0.90**; cumulative-return divergence ≤ **3 percentage points**.
- **Gate 2** (design §5): **zero** unresolved reconciliation breaks across the paper period; kill switch tested under load; order lifecycle exercised including partial fills, rejections, and a trading halt.
- **Gate 3** (design §6): NZ$100 ≈ US$60, budget 3–8 trades. Proves wiring, **not** profitability.
- Every existing recorded result must stay reproducible: new behaviour is opt-in, defaults unchanged.
- Costs: IBKR **Tiered** commission, 5bp spread. Never Fixed.
- The delegate harness writes production code; **tests are written by the reviewer, never by the delegate**.
- No parameter may be tuned by looking at Gate 0 output. Thresholds are constants set in advance.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/ghambla/backtest.py` | Backtest engine | Modify — add `cash_buffer`, live-parity |
| `src/ghambla/cycle.py` | Live daily cycle | Modify — add `regime_filter` |
| `src/ghambla/cli.py` | Entry points | Modify — `--live-parity`, ingest wiring |
| `src/ghambla/ibkr.py` | IBKR adapter | Modify — lifecycle hardening |
| `tests/test_backtest.py` | Backtest tests | Modify |
| `tests/test_cycle.py` | Cycle tests | Modify |
| `tests/test_ibkr.py` | Adapter tests | Modify |
| `tests/test_live_parity.py` | **New** — asserts backtest and cycle agree | Create |
| `docs/analysis/gate0_matrix.md` | **New** — pre-registered Gate 0 results | Create |

---

## Phase A — Close the last validate/run gaps

Gate 0 is worthless as a predictor while the backtest and the cycle do different things. Two divergences remain, found by auditing which symbols appear in only one file.

### Task 1: Cash buffer in the backtest

The cycle holds back 2% of equity (`CASH_BUFFER`) because sizing to exactly 100% invested guarantees the final buy is rejected — commission has to come from somewhere. The backtest sizes to 100%, so it books trades the live system would reject.

**Files:**
- Modify: `src/ghambla/backtest.py` (`run_backtest` signature; the `equity_at_open` line)
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `CASH_BUFFER` from `ghambla.cycle`
- Produces: `run_backtest(..., cash_buffer: float = 0.0)`

- [ ] **Step 1: Write the failing test**

```python
def test_cash_buffer_leaves_equity_uninvested(store):
    """The cycle holds back 2% so the last buy is not rejected for commission.

    A backtest that deploys 100% books fills the live system would refuse.
    """
    full = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                        initial_cash=10_000.0, top_n=1)
    buffered = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                            initial_cash=10_000.0, top_n=1, cash_buffer=0.02)
    spent_full = sum(t.shares * t.price for t in full.trades if t.side == "BUY")
    spent_buf = sum(t.shares * t.price for t in buffered.trades if t.side == "BUY")
    assert spent_buf < spent_full
    assert spent_buf == pytest.approx(spent_full * 0.98, rel=0.02)


def test_cash_buffer_defaults_to_zero(store):
    """Recorded Gate 0 numbers were produced with no buffer."""
    a = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0)
    b = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0, cash_buffer=0.0)
    assert a.equity == b.equity
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_backtest.py -k cash_buffer -q`
Expected: FAIL — `run_backtest() got an unexpected keyword argument 'cash_buffer'`

- [ ] **Step 3: Implement**

Add the parameter after `risk_gate`:

```python
                 risk_gate=None, cash_buffer: float = 0.0
```

and scale the sizing base:

```python
            # Match the live cycle: sizing to exactly 100% invested guarantees
            # the final buy is rejected, because commission has to come from
            # somewhere and a fill can print slightly above the reference price.
            equity_at_open = (cash + sum(sh * opens.get(sym, 0.0)
                                         for sym, sh in positions.items())) \
                * (1.0 - cash_buffer)
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS, count increased by 2.

- [ ] **Step 5: Commit**

```bash
git add src/ghambla/backtest.py tests/test_backtest.py
git commit -m "Give the backtest the cycle's cash buffer"
```

### Task 2: Regime filter in the live cycle

`trend_filter` appears 3 times in `backtest.py` and 0 times in `cycle.py`. Enabling it for Gate 0 today would measure a strategy the live cycle cannot run — the same defect, freshly introduced.

**Files:**
- Modify: `src/ghambla/cycle.py` (`DailyCycle.__init__`, `run`)
- Test: `tests/test_cycle.py`

**Interfaces:**
- Consumes: `trend_filter(store, as_of, symbol, lookback) -> bool | None` from `ghambla.regime`
- Produces: `DailyCycle(..., regime_filter: bool = False, regime_lookback: int = 200)`

- [ ] **Step 1: Write the failing test**

```python
def test_cycle_regime_filter_holds_cash_when_it_cannot_evaluate(store, tmp_path):
    """Fails closed, exactly as the backtest does. No SPY history in the fixture."""
    broker = SimulatedBroker(cash=10_000.0, spread_bps=0.0)
    broker.connect()
    cycle = DailyCycle(store, {"m": Likes(["AAA", "BBB"])}, broker,
                       Journal(tmp_path / "rg.jsonl"), mode="paper",
                       risk_gate=RiskGate(RiskLimits(max_position_weight=1.0)),
                       top_n=2, regime_filter=True, regime_lookback=5)
    r = cycle.run(d("2026-08-06"))
    assert r.targets == {}
    assert broker.snapshot().positions == {}


def test_cycle_regime_filter_is_off_by_default(store, tmp_path):
    cycle, broker, _ = make(store, tmp_path)
    r = cycle.run(d("2026-08-06"))
    assert set(r.targets) == {"AAA", "BBB"}
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_cycle.py -k regime -q`
Expected: FAIL — unexpected keyword argument `regime_filter`

- [ ] **Step 3: Implement**

In `cycle.py`, import and store the setting:

```python
from .regime import trend_filter
```

```python
                 weighting: str = "equal", regime_filter: bool = False,
                 regime_lookback: int = 200) -> None:
    ...
    self.regime_filter = regime_filter
    self.regime_lookback = regime_lookback
```

In `run`, before building `RiskState`:

```python
        # `is not True`, not `is False`: trend_filter returns None when it
        # cannot be evaluated, and an unknown regime must fail closed.
        risk_on = trend_filter(self.store, as_of,
                               lookback=self.regime_lookback) \
            if self.regime_filter else None
```

and pass `risk_on=risk_on` into the existing `RiskState(...)` construction. The gate already empties targets when `risk_on is False`; add the fail-closed case:

```python
        if self.regime_filter and risk_on is not True:
            risk_on = False
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ghambla/cycle.py tests/test_cycle.py
git commit -m "Give the live cycle the backtest's regime filter"
```

### Task 3: A test that fails when the two paths diverge again

Two divergences were found by hand. A third will appear unless something watches for it.

**Files:**
- Create: `tests/test_live_parity.py`

**Interfaces:**
- Consumes: `run_backtest`, `DailyCycle`, `SimulatedBroker`, `Journal`

- [ ] **Step 1: Write the test**

```python
"""The backtest and the live cycle must produce the same targets.

The design doc's rule: one decision path, three execution backends. Any logic
in only one path is a bug waiting to happen. Two such bugs have already
shipped — the scorer and the risk gate — and both were found by hand. This
test finds the third.
"""
import datetime as dt
import inspect

import pytest

from ghambla import backtest, cycle


def test_every_decision_knob_exists_on_both_paths():
    """A parameter that shapes decisions must be honoured by both engines."""
    bt = set(inspect.signature(backtest.run_backtest).parameters)
    cy = set(inspect.signature(cycle.DailyCycle.__init__).parameters)
    shared = {"top_n", "weighting", "regime_filter", "risk_gate", "cash_buffer"}
    missing_bt = shared - bt
    missing_cy = shared - cy
    assert not missing_bt, f"backtest is missing decision knobs: {missing_bt}"
    assert not missing_cy, f"cycle is missing decision knobs: {missing_cy}"


def test_same_signal_and_day_gives_the_same_targets(tmp_path):
    """The strongest form: run both engines on one day and compare targets."""
    from ghambla.broker import SimulatedBroker
    from ghambla.journal import Journal
    from ghambla.risk import RiskGate, RiskLimits
    from ghambla.signals.base import Score
    from ghambla.store.store import Bar, FeatureStore

    class Likes:
        name = "likes"

        def score(self, store, as_of, universe):
            order = ["AAA", "BBB", "CCC"]
            return {s: Score(value=float(len(order) - order.index(s))
                             if s in order else -1.0,
                             confidence=1.0, rationale="stub")
                    for s in universe}

    store = FeatureStore(tmp_path / "parity.db")
    day = dt.date(2026, 1, 1)
    bars = []
    for _ in range(40):
        for sym, px in (("AAA", 100.0), ("BBB", 50.0), ("CCC", 25.0)):
            bars.append(Bar(sym, day, px, px, px, px, px, 10_000))
        day += dt.timedelta(days=1)
    store.upsert_bars(bars)
    store.set_universe(dt.date(2025, 12, 1), ["AAA", "BBB", "CCC"])
    try:
        as_of = store.trading_dates(dt.date(2026, 1, 1), dt.date(2026, 2, 9))[-1]
        gate = RiskGate(RiskLimits(max_position_weight=1.0))

        broker = SimulatedBroker(cash=10_000.0, spread_bps=0.0)
        broker.connect()
        c = cycle.DailyCycle(store, {"m": Likes()}, broker,
                             Journal(tmp_path / "p.jsonl"), mode="paper",
                             risk_gate=gate, top_n=2)
        cycle_targets = c.run(as_of).targets

        scores = backtest.score_universe(store, as_of, ["AAA", "BBB", "CCC"],
                                         {"m": Likes()},
                                         backtest.RankAllocator())
        bt_targets = {t.symbol: t.weight
                      for t in backtest.weigh(scores, 2, "equal", store, as_of, 252)}
        assert set(cycle_targets) == set(bt_targets)
    finally:
        store.close()
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/pytest tests/test_live_parity.py -q`
Expected: PASS once Tasks 1 and 2 are done. If it fails, a knob is missing on one side — that is the point.

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_parity.py
git commit -m "Assert the backtest and live cycle cannot silently diverge"
```

### Task 4: Single `--live-parity` flag

Three separate flags is three chances to measure the wrong thing.

**Files:**
- Modify: `src/ghambla/cli.py`

- [ ] **Step 1: Implement**

```python
    pb.add_argument("--live-parity", action="store_true",
                    help="measure exactly what the live cycle would run: "
                         "risk gate on, cash buffer on")
```

In `cmd_backtest` and `cmd_evaluate`:

```python
        from .cycle import CASH_BUFFER
        risk_gate = RiskGate() if (args.risk_gate or args.live_parity) else None
        cash_buffer = CASH_BUFFER if args.live_parity else 0.0
```

- [ ] **Step 2: Verify both flags reach the engine**

Run: `.venv/bin/python -m ghambla.cli backtest --live-parity --start 2025-01-01 --end 2025-06-01`
Expected: completes; trade count lower than without the flag.

- [ ] **Step 3: Commit**

```bash
git add src/ghambla/cli.py
git commit -m "Add --live-parity so Gate 0 measures the live configuration"
```

---

## Phase B — Complete the dataset

The bar ingest back to 2000 is running. **Splits and fundamentals were only ever ingested for the 2016–2026 window**, so the fundamental signal and split adjustment are blind before 2016. Evaluating on 26 years without this would produce a confidently wrong number.

### Task 5: Extend splits and fundamentals to the full window

**Files:** none — CLI operations only.

- [ ] **Step 1: Wait for the bar ingest to finish**

Run: `ps -eo etime,cmd | grep "cli ingest" | grep -v grep`
Expected: no output. Do not proceed while it runs; the DB is mid-write.

- [ ] **Step 2: Ingest splits for the full window**

```bash
.venv/bin/python -m ghambla.cli ingest-splits --start 2000-01-01 --end 2026-08-01 --pause 0.25
```

- [ ] **Step 3: Ingest fundamentals for the full window**

```bash
.venv/bin/python -m ghambla.cli ingest-fundamentals --start 2000-01-01 --end 2026-08-01 --pause 0.3
```

- [ ] **Step 4: Record coverage honestly**

```bash
.venv/bin/python -c "
import json; d = json.load(open('data/coverage.json'))
print(d['window'], d['priced'], '/', d['requested'], f\"{d['coverage']:.1%}\")"
```

Coverage **will** be worse than 84.7% — vendors serve less history for dead tickers, and survivorship bias grows as the window lengthens. Write the new number into `README.md` under "Residual bias, still present" **before** looking at any performance result, so the caveat cannot be tuned to suit the outcome.

- [ ] **Step 5: Commit**

```bash
git add data/coverage.json README.md
git commit -m "Extend splits and fundamentals to 2000; record degraded coverage"
```

---

## Phase C — Re-baseline Gate 0, pre-registered

Five candidates have been tested on 2018–2026. Every additional test on the same data raises the chance a pass is noise. The extended window is a genuinely new sample, and it must not be squandered by fishing.

### Task 6: Write the pre-registration BEFORE running anything

**Files:**
- Create: `docs/analysis/gate0_matrix.md`

- [ ] **Step 1: Write the document, results section empty**

```markdown
# Gate 0 re-baseline on 2000–2026 — pre-registration

Written before any result on this window was seen.

## Primary candidate (the one that counts)

`momentum`, equal weighting, `--regime-filter`, `--live-parity`.

Chosen because both additions follow from measurement, not from fitting:
the correlation probe showed the book is only modestly more correlated than
random (+0.394 vs +0.282), so drawdown comes from being ~100% net long, and a
trend filter is the standard remedy at its standard 200-day parameterisation.

## Secondary candidates (reported, not decisive)

- momentum, equal, no filter, live-parity — isolates what the filter is worth
- momentum, equal, no filter, no gate — reproduces the 2018–2026 baseline
- lowvol, equal, regime filter, live-parity
- momentum+fundamental, equal, regime filter, live-parity

## Decision rule, fixed in advance

The PRIMARY candidate decides Gate 0. A secondary candidate passing while the
primary fails is a multiple-comparisons artefact and does NOT advance to paper.

## Results

(to be filled in — one run each, no reruns with adjusted parameters)
```

- [ ] **Step 2: Commit before running**

```bash
git add docs/analysis/gate0_matrix.md
git commit -m "Pre-register the Gate 0 re-baseline before seeing any result"
```

### Task 7: Run the matrix, once each

- [ ] **Step 1: Primary candidate**

```bash
.venv/bin/python -m ghambla.cli evaluate --signal momentum \
  --regime-filter --live-parity \
  --start 2000-01-01 --end 2026-08-01 --top-n 10 --rebalance-every 21
```

- [ ] **Step 2: Secondary candidates**

Run each of the four listed above, changing only the stated flags.

- [ ] **Step 3: Paste every result into `docs/analysis/gate0_matrix.md` verbatim**

Including failures. Especially failures.

- [ ] **Step 4: Update `README.md`**

Add a 2000–2026 row to the walk-forward table. If the primary fails, say so in the status line at the top of the file.

- [ ] **Step 5: Commit**

```bash
git add docs/analysis/gate0_matrix.md README.md
git commit -m "Record the Gate 0 re-baseline on 2000-2026"
```

### Decision point

**If the primary candidate FAILS:** stop. Do not proceed to Phase D. Six candidates will have failed a pre-registered gate across 26 years including the dot-com unwind, the GFC, and the 2009 momentum crash. That is a real finding and the honest response is to record it and stop trading work — not to search for a seventh. The plumbing test may still be run deliberately as an engineering exercise, but it must be labelled as such in the README, and no strategy may be represented as validated.

**If it PASSES:** continue to Phase D.

---

## Phase D — IBKR paper readiness

`ibkr.py` carries the comment *"Unit-tested only — never run against a real gateway."* Gate 1 needs 60 days of it working unattended.

### Task 8: Connection smoke test against a live paper gateway

**Files:**
- Create: `tests/test_ibkr_integration.py` (marked, skipped by default)

- [ ] **Step 1: Write the test**

```python
"""Integration tests against a REAL IB Gateway paper session.

Skipped unless GHAMBLA_IBKR_INTEGRATION=1. These cost nothing but require a
running gateway logged into a PAPER account on port 4002.
"""
import os

import pytest

from ghambla.ibkr import IBKRBroker

pytestmark = pytest.mark.skipif(
    os.environ.get("GHAMBLA_IBKR_INTEGRATION") != "1",
    reason="needs a running IB Gateway paper session")


def test_connects_and_reports_an_account():
    broker = IBKRBroker(port=4002)
    broker.connect()
    try:
        snap = broker.snapshot()
        assert snap.cash > 0, "paper account has no cash; fund it in TWS"
    finally:
        broker.disconnect()


def test_reconnect_after_disconnect_is_clean():
    """The scheduler runs daily for 60 days; a stale socket must not wedge it."""
    broker = IBKRBroker(port=4002)
    broker.connect()
    broker.disconnect()
    broker.connect()
    try:
        assert broker.snapshot() is not None
    finally:
        broker.disconnect()
```

- [ ] **Step 2: Start IB Gateway logged into the paper account, port 4002**

- [ ] **Step 3: Run**

Run: `GHAMBLA_IBKR_INTEGRATION=1 .venv/bin/pytest tests/test_ibkr_integration.py -q`
Expected: PASS. Any failure here is a real adapter defect — fix it before proceeding.

- [ ] **Step 4: Commit**

```bash
git add tests/test_ibkr_integration.py
git commit -m "Add opt-in IBKR paper gateway integration tests"
```

### Task 9: Order lifecycle — the Gate 2 requirements

Gate 2 requires partial fills, rejections, and a trading halt to be exercised. Do it on paper, deliberately, rather than discovering them live.

- [ ] **Step 1: Rejection** — place an order for more than the account can afford; assert `OrderError` is raised, the cycle survives, and the journal records `order rejected`.
- [ ] **Step 2: Partial fill** — place a large order in an illiquid name; assert the `Fill` reports fewer shares than requested and reconciliation still balances.
- [ ] **Step 3: Halt** — run `cycle --halt`; assert zero orders, `halted=True`, and a journal entry giving the reason.
- [ ] **Step 4: Kill switch under load** — start the scheduler, trigger `--halt` mid-cycle, assert no orders escape.
- [ ] **Step 5: Write each observed behaviour into `tests/test_ibkr_integration.py`** as an assertion, so it is checked from then on.
- [ ] **Step 6: Commit**

### Task 10: Unattended scheduler

- [ ] **Step 1: Install a cron entry or systemd timer** running `ghambla-scheduler --broker ibkr` once daily after the US close.
- [ ] **Step 2: Verify it survives a WSL restart** (the `.wslconfig` memory cap is already in place).
- [ ] **Step 3: Confirm a journal line appears every scheduled day, including days it halted.** A day that halted without recording why is indistinguishable from a day that never ran.
- [ ] **Step 4: Commit any configuration into the repo.**

---

## Phase E — Gate 1, the paper run

### Task 11: Run 60 trading days

- [ ] **Step 1: Run the scheduler daily.** Roughly 12 calendar weeks. There is no way to compress this and no reason to try.
- [ ] **Step 2: Weekly, run** `.venv/bin/python -m ghambla.cli journal --tail 20` **and read it.** Anything surprising is a defect, not a curiosity.
- [ ] **Step 3: Any reconciliation break halts the run.** Fix the cause, then restart the 60-day count from zero. Gate 2 requires *zero unresolved breaks across the entire paper period*.
- [ ] **Step 4: At 60 days and 30 trades, run the Gate 1 check:**

```bash
.venv/bin/python -m ghambla.cli papercheck --start <first-paper-day> --end <last-paper-day>
```

- [ ] **Step 5: Apply the pre-registered rule.** Correlation ≥ 0.90 and cumulative divergence ≤ 3pp. Below either: **the backtest is wrong, and the fix is to the backtest, not to the trading.** Diagnose using the journal's per-signal rationale, fix, and re-run the paper period.

---

## Phase F — Gate 3, the NZ$100 live plumbing test

### Task 12: The live run

- [ ] **Step 1: Confirm Gate 2 is met** — zero unresolved reconciliation breaks, kill switch tested under load, full lifecycle exercised.
- [ ] **Step 2: Fund the live account with NZ$100.** Roughly US$60.
- [ ] **Step 3: Set `top_n` so position count suits US$60.** With IBKR Tiered capping commission at 1% of trade value, 2–3 positions is the realistic ceiling. Ten positions of US$6 is all cost and no signal.
- [ ] **Step 4: Run** `cycle --broker ibkr --live` **with the gateway logged into the LIVE account.** Note the design doc's warning: `--live` only selects the port; *the account the gateway is logged into is what decides whether the money is real.*
- [ ] **Step 5: Budget 3–8 trades, then stop.**
- [ ] **Step 6: Verify against the journal** — every order has a fill, every fill reconciles, cash and positions match the broker exactly.
- [ ] **Step 7: Write the outcome into `README.md`,** with the design doc's caveat stated plainly: *with ~2% round-trip costs on US$60 and a handful of trades, profit or loss is statistically indistinguishable from noise. Making money is not evidence the strategy works; losing money is not evidence it does not.*

---

## Self-review notes

- **Spec coverage:** Gate 0 → Phase C. Gate 1 → Phase E (papercheck already implemented). Gate 2 → Tasks 9–10. Gate 3 → Task 12. Design §3's "one decision path" rule → Phase A.
- **Known gap accepted:** survivorship bias grows with the longer window; Task 5 Step 4 requires recording it before results are seen.
- **Sequencing risk:** Phase C's decision point can end the plan. That is intentional. A plan that cannot conclude "this does not work" is not a plan, it is a commitment.
