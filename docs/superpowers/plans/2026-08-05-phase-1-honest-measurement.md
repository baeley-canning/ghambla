# Phase 1: Honest Measurement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a backtest you have reason to trust — a point-in-time feature store, an IBKR-accurate cost model, one deliberately simple momentum signal, and an evaluation harness that compares it honestly against SPY buy-and-hold.

**Architecture:** All market data lands in SQLite with a `knowable_at` column recording when each fact became knowable. Every read goes through `bars_as_of(as_of)`, which physically cannot return a row stamped later than `as_of`. Signals are pure functions over that store. The backtest fills orders at the *next* bar's open, never the close of the bar that generated the signal. A planted-lookahead test proves the guarantee holds.

**Tech Stack:** Python 3.12, standard library only at runtime (`sqlite3`, `urllib`, `json`, `datetime`, `dataclasses`, `math`, `statistics`). `pytest` as the only dev dependency. Historical data from the Yahoo Finance chart endpoint.

## Global Constraints

- Python 3.12+. Runtime code imports **standard library only** — no pandas, numpy, or requests. `pytest` is a dev dependency only.
- Rationale for stdlib-only: ~100 symbols × 10 years of daily bars is ~250k rows, which SQLite handles trivially. Explicit SQL makes the point-in-time guarantee auditable by reading it, where pandas indexing would hide it. Revisit only if profiling shows a real bottleneck.
- Every table storing a fact carries a `knowable_at DATE NOT NULL` column. No exceptions.
- No read path may accept an `as_of` and return rows with `knowable_at > as_of`. This is the project's central invariant.
- Money is `float` in Phase 1 (backtest only, no real orders). Revisit before Phase 3.
- Commission model is IBKR **Tiered**: `USD 0.0035/share, minimum USD 0.35 per order, maximum 1% of trade value`. The 1% cap is what makes small trades viable and must be tested explicitly.
- All dates are `datetime.date`, never `datetime.datetime`, and never strings outside the SQLite layer.
- Package lives at repository root as `src/ghambla/`.

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, pytest config |
| `src/ghambla/__init__.py` | Package marker, version |
| `src/ghambla/store/schema.py` | SQLite DDL, one constant per table |
| `src/ghambla/store/store.py` | `FeatureStore` — the only way to read data |
| `src/ghambla/store/ingest.py` | `DataSource` protocol, `YahooDataSource` |
| `src/ghambla/signals/base.py` | `Score` dataclass, `Signal` protocol |
| `src/ghambla/signals/momentum.py` | 12-1 momentum signal |
| `src/ghambla/costs.py` | IBKR Tiered commission |
| `src/ghambla/portfolio.py` | Scores → target weights |
| `src/ghambla/backtest.py` | Engine with next-open fills |
| `src/ghambla/evaluate.py` | Sharpe, max drawdown, benchmark comparison |
| `src/ghambla/cli.py` | `python -m ghambla.cli` entry points |
| `tests/test_costs.py` | Cost model, including the 1% cap |
| `tests/test_store.py` | Store round-trip, universe snapshots |
| `tests/test_pointintime.py` | The central invariant + planted lookahead bug |
| `tests/test_momentum.py` | Signal correctness |
| `tests/test_portfolio.py` | Weight construction |
| `tests/test_backtest.py` | Next-open fill rule, cash accounting |
| `tests/test_evaluate.py` | Metrics against hand-computed values |

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`, `src/ghambla/__init__.py`, `tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing
- Produces: importable package `ghambla` with `__version__: str`

- [ ] **Step 1: Create the venv and install pytest**

```bash
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip pytest
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "ghambla"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 3: Write the failing smoke test**

```python
# tests/test_smoke.py
def test_package_imports():
    import ghambla
    assert ghambla.__version__ == "0.1.0"
```

- [ ] **Step 4: Run it and watch it fail**

Run: `.venv/bin/pytest tests/test_smoke.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'ghambla'`

- [ ] **Step 5: Create the package**

```python
# src/ghambla/__init__.py
"""Automated trading research platform."""

__version__ = "0.1.0"
```

- [ ] **Step 6: Run it and watch it pass**

Run: `.venv/bin/pytest -v` → 1 passed

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src tests
git commit -m "Add Python package scaffold with pytest"
```

---

### Task 2: IBKR Tiered cost model

Done early because it is self-contained, and because the 1% cap is the single number the NZ$100 live test depends on.

**Files:**
- Create: `src/ghambla/costs.py`, `tests/test_costs.py`

**Interfaces:**
- Consumes: nothing
- Produces: `ibkr_tiered_commission(shares: float, price: float) -> float`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_costs.py
import pytest
from ghambla.costs import ibkr_tiered_commission


def test_per_share_rate_applies_on_large_orders():
    # 1000 shares @ $50: 1000 * 0.0035 = 3.50, well under the 1% cap of $500
    assert ibkr_tiered_commission(1000, 50.0) == pytest.approx(3.50)


def test_minimum_charge_applies_on_small_share_counts():
    # 10 shares @ $500 = $5000 notional. Per-share is $0.035, so the $0.35
    # minimum binds. The 1% cap ($50) is far away.
    assert ibkr_tiered_commission(10, 500.0) == pytest.approx(0.35)


def test_one_percent_cap_beats_the_minimum_on_tiny_trades():
    # THE case the NZ$100 live test depends on.
    # 1 share @ $30 = $30 notional. Minimum would be $0.35, but 1% is $0.30.
    # The cap wins, so the trade costs $0.30 not $0.35.
    assert ibkr_tiered_commission(1, 30.0) == pytest.approx(0.30)


def test_one_percent_cap_on_fractional_shares():
    # 0.5 shares @ $20 = $10 notional. Cap is $0.10.
    assert ibkr_tiered_commission(0.5, 20.0) == pytest.approx(0.10)


def test_zero_shares_costs_nothing():
    assert ibkr_tiered_commission(0, 100.0) == 0.0


def test_rejects_negative_inputs():
    with pytest.raises(ValueError):
        ibkr_tiered_commission(-1, 100.0)
    with pytest.raises(ValueError):
        ibkr_tiered_commission(1, -100.0)
```

- [ ] **Step 2: Run and watch them fail**

Run: `.venv/bin/pytest tests/test_costs.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'ghambla.costs'`

- [ ] **Step 3: Implement**

```python
# src/ghambla/costs.py
"""IBKR Tiered commission model.

Tiered pricing is mandatory for this project rather than merely preferred.
Fixed pricing charges USD 1.00 minimum per order, which on a USD 30 position
is 3.3% each way. Tiered caps commission at 1% of trade value, so the same
trade costs USD 0.30. See the design doc, section 6.
"""

PER_SHARE = 0.0035
MIN_PER_ORDER = 0.35
MAX_FRACTION_OF_VALUE = 0.01


def ibkr_tiered_commission(shares: float, price: float) -> float:
    """Commission for one order, in USD.

    Exchange, regulatory and clearing fees are passed through by IBKR on top
    of this and are not modelled here; they are small relative to the spread
    assumption in the backtest.
    """
    if shares < 0 or price < 0:
        raise ValueError(f"shares and price must be non-negative, got {shares=} {price=}")
    if shares == 0 or price == 0:
        return 0.0

    notional = shares * price
    commission = max(PER_SHARE * shares, MIN_PER_ORDER)
    return min(commission, MAX_FRACTION_OF_VALUE * notional)
```

- [ ] **Step 4: Run and watch them pass**

Run: `.venv/bin/pytest tests/test_costs.py -v` → 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/ghambla/costs.py tests/test_costs.py
git commit -m "Add IBKR Tiered commission model with 1% cap"
```

---

### Task 3: Store schema and `FeatureStore` read path

**Files:**
- Create: `src/ghambla/store/__init__.py`, `src/ghambla/store/schema.py`, `src/ghambla/store/store.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `Bar` frozen dataclass: `symbol: str, date: date, open: float, high: float, low: float, close: float, adj_close: float, volume: int`
  - `FeatureStore(db_path: str | Path)` with `upsert_bars(bars: Iterable[Bar]) -> int`, `bars_as_of(as_of: date, symbols: Sequence[str], lookback: int) -> dict[str, list[Bar]]`, `set_universe(effective: date, symbols: Sequence[str]) -> None`, `universe_as_of(as_of: date) -> list[str]`, `trading_dates(start: date, end: date) -> list[date]`, `close()`

**Design note for the implementer:** a daily bar for date D becomes knowable at D's close, so `knowable_at = date`. This is why a decision made "as of D" may use bar D, and why the backtest must then fill at D+1's open. Fundamentals in Phase 4 will set `knowable_at` to the *report* date, not the period end — the column exists now so that later change needs no migration.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_store.py
import datetime as dt
import pytest
from ghambla.store.store import Bar, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def bar(sym: str, day: str, close: float) -> Bar:
    return Bar(symbol=sym, date=d(day), open=close, high=close, low=close,
               close=close, adj_close=close, volume=1000)


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "test.db")
    yield s
    s.close()


def test_upsert_then_read_back(store):
    store.upsert_bars([bar("AAPL", "2026-01-05", 100.0)])
    got = store.bars_as_of(d("2026-01-05"), ["AAPL"], lookback=10)
    assert len(got["AAPL"]) == 1
    assert got["AAPL"][0].close == 100.0


def test_upsert_is_idempotent(store):
    store.upsert_bars([bar("AAPL", "2026-01-05", 100.0)])
    store.upsert_bars([bar("AAPL", "2026-01-05", 101.0)])
    got = store.bars_as_of(d("2026-01-05"), ["AAPL"], lookback=10)
    assert len(got["AAPL"]) == 1
    assert got["AAPL"][0].close == 101.0


def test_bars_are_returned_oldest_first(store):
    store.upsert_bars([bar("AAPL", "2026-01-07", 102.0),
                       bar("AAPL", "2026-01-05", 100.0),
                       bar("AAPL", "2026-01-06", 101.0)])
    got = store.bars_as_of(d("2026-01-07"), ["AAPL"], lookback=10)
    assert [b.date for b in got["AAPL"]] == [d("2026-01-05"), d("2026-01-06"), d("2026-01-07")]


def test_lookback_returns_the_most_recent_n_bars(store):
    store.upsert_bars([bar("AAPL", f"2026-01-{day:02d}", 100.0 + day) for day in range(5, 15)])
    got = store.bars_as_of(d("2026-01-14"), ["AAPL"], lookback=3)
    assert [b.date for b in got["AAPL"]] == [d("2026-01-12"), d("2026-01-13"), d("2026-01-14")]


def test_missing_symbol_yields_empty_list_not_keyerror(store):
    store.upsert_bars([bar("AAPL", "2026-01-05", 100.0)])
    got = store.bars_as_of(d("2026-01-05"), ["AAPL", "MSFT"], lookback=10)
    assert got["MSFT"] == []


def test_universe_membership_is_dated(store):
    store.set_universe(d("2026-01-01"), ["AAPL", "MSFT"])
    store.set_universe(d("2026-06-01"), ["AAPL", "MSFT", "NVDA"])
    assert store.universe_as_of(d("2026-03-01")) == ["AAPL", "MSFT"]
    assert store.universe_as_of(d("2026-07-01")) == ["AAPL", "MSFT", "NVDA"]


def test_universe_before_any_snapshot_is_empty(store):
    store.set_universe(d("2026-01-01"), ["AAPL"])
    assert store.universe_as_of(d("2025-12-31")) == []


def test_trading_dates_are_the_dates_we_actually_have_bars_for(store):
    store.upsert_bars([bar("AAPL", "2026-01-05", 100.0),
                       bar("MSFT", "2026-01-05", 200.0),
                       bar("AAPL", "2026-01-06", 101.0)])
    assert store.trading_dates(d("2026-01-01"), d("2026-01-31")) == [d("2026-01-05"), d("2026-01-06")]
```

- [ ] **Step 2: Run and watch them fail**

Run: `.venv/bin/pytest tests/test_store.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'ghambla.store'`

- [ ] **Step 3: Write the schema**

```python
# src/ghambla/store/schema.py
"""SQLite DDL.

Every table storing a fact carries `knowable_at`: the date on which that fact
became knowable to a trader. All reads filter on it. This is the mechanism
that makes lookahead bias structurally impossible rather than merely
discouraged.
"""

BARS = """
CREATE TABLE IF NOT EXISTS bars (
    symbol      TEXT NOT NULL,
    date        TEXT NOT NULL,
    open        REAL NOT NULL,
    high        REAL NOT NULL,
    low         REAL NOT NULL,
    close       REAL NOT NULL,
    adj_close   REAL NOT NULL,
    volume      INTEGER NOT NULL,
    knowable_at TEXT NOT NULL,
    PRIMARY KEY (symbol, date)
);
"""

BARS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_bars_knowable
    ON bars (symbol, knowable_at);
"""

UNIVERSE = """
CREATE TABLE IF NOT EXISTS universe (
    effective   TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    knowable_at TEXT NOT NULL,
    PRIMARY KEY (effective, symbol)
);
"""

ALL = [BARS, BARS_INDEX, UNIVERSE]
```

- [ ] **Step 4: Write the store**

Implementation notes the implementer must follow exactly:
- `bars_as_of` filters `knowable_at <= :as_of`, orders `date DESC LIMIT :lookback` in a subquery, then re-sorts ascending in Python so callers always get oldest-first.
- `universe_as_of` selects symbols from the single most recent `effective` that is `<= as_of`.
- Store dates as ISO strings; convert at the boundary so no ISO string escapes the module.
- Use `sqlite3.connect(..., detect_types=0)` and explicit conversion — no type-detection magic.

```python
# src/ghambla/store/store.py
import datetime as dt
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from . import schema


@dataclass(frozen=True)
class Bar:
    symbol: str
    date: dt.date
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int


class FeatureStore:
    """The only way to read market data.

    Every read takes an `as_of` date and can only return facts that were
    knowable on or before it.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        for ddl in schema.ALL:
            self._conn.execute(ddl)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def upsert_bars(self, bars: Iterable[Bar]) -> int:
        rows = [
            (b.symbol, b.date.isoformat(), b.open, b.high, b.low, b.close,
             b.adj_close, b.volume, b.date.isoformat())
            for b in bars
        ]
        self._conn.executemany(
            "INSERT INTO bars (symbol, date, open, high, low, close, adj_close, volume, knowable_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(symbol, date) DO UPDATE SET"
            " open=excluded.open, high=excluded.high, low=excluded.low,"
            " close=excluded.close, adj_close=excluded.adj_close, volume=excluded.volume",
            rows,
        )
        self._conn.commit()
        return len(rows)

    def bars_as_of(self, as_of: dt.date, symbols: Sequence[str], lookback: int) -> dict[str, list[Bar]]:
        out: dict[str, list[Bar]] = {}
        for symbol in symbols:
            cur = self._conn.execute(
                "SELECT * FROM bars WHERE symbol = ? AND knowable_at <= ?"
                " ORDER BY date DESC LIMIT ?",
                (symbol, as_of.isoformat(), lookback),
            )
            found = [self._to_bar(r) for r in cur.fetchall()]
            found.reverse()
            out[symbol] = found
        return out

    def set_universe(self, effective: dt.date, symbols: Sequence[str]) -> None:
        self._conn.executemany(
            "INSERT OR REPLACE INTO universe (effective, symbol, knowable_at) VALUES (?,?,?)",
            [(effective.isoformat(), s, effective.isoformat()) for s in symbols],
        )
        self._conn.commit()

    def universe_as_of(self, as_of: dt.date) -> list[str]:
        cur = self._conn.execute(
            "SELECT symbol FROM universe WHERE effective = ("
            "  SELECT MAX(effective) FROM universe WHERE knowable_at <= ?"
            ") ORDER BY symbol",
            (as_of.isoformat(),),
        )
        return [r["symbol"] for r in cur.fetchall()]

    def trading_dates(self, start: dt.date, end: dt.date) -> list[dt.date]:
        cur = self._conn.execute(
            "SELECT DISTINCT date FROM bars WHERE date >= ? AND date <= ? ORDER BY date",
            (start.isoformat(), end.isoformat()),
        )
        return [dt.date.fromisoformat(r["date"]) for r in cur.fetchall()]

    @staticmethod
    def _to_bar(r: sqlite3.Row) -> Bar:
        return Bar(symbol=r["symbol"], date=dt.date.fromisoformat(r["date"]),
                   open=r["open"], high=r["high"], low=r["low"], close=r["close"],
                   adj_close=r["adj_close"], volume=r["volume"])
```

Also create an empty `src/ghambla/store/__init__.py`.

- [ ] **Step 5: Run and watch them pass**

Run: `.venv/bin/pytest tests/test_store.py -v` → 8 passed

- [ ] **Step 6: Commit**

```bash
git add src/ghambla/store tests/test_store.py
git commit -m "Add point-in-time feature store with dated universe snapshots"
```

---

### Task 4: The point-in-time invariant, with a planted lookahead bug

This is the task the whole phase exists for. Gate 0 in the design doc requires that a deliberately injected lookahead bug is caught by the suite.

**Files:**
- Create: `tests/test_pointintime.py`

**Interfaces:**
- Consumes: `FeatureStore`, `Bar` from Task 3
- Produces: nothing importable; a guarantee

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pointintime.py
"""The central invariant: no read may return a fact from the future.

`test_planted_lookahead_bug_is_caught` is required by Gate 0 of the design
doc. It proves the suite can actually detect lookahead, rather than merely
asserting that correct code is correct.
"""
import datetime as dt
import pytest
from ghambla.store.store import Bar, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def bar(sym: str, day: str, close: float) -> Bar:
    return Bar(symbol=sym, date=d(day), open=close, high=close, low=close,
               close=close, adj_close=close, volume=1000)


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "pit.db")
    s.upsert_bars([bar("AAPL", f"2026-01-{day:02d}", 100.0 + day) for day in range(5, 26)])
    yield s
    s.close()


def test_future_bars_are_never_returned(store):
    got = store.bars_as_of(d("2026-01-15"), ["AAPL"], lookback=100)
    assert max(b.date for b in got["AAPL"]) == d("2026-01-15")


def test_no_returned_bar_postdates_the_as_of_for_any_as_of(store):
    # Property test across every as-of date in range.
    for day in range(5, 26):
        as_of = d(f"2026-01-{day:02d}")
        got = store.bars_as_of(as_of, ["AAPL"], lookback=100)
        assert all(b.date <= as_of for b in got["AAPL"]), f"leak at {as_of}"


def test_data_ingested_later_does_not_change_an_earlier_as_of_view(store):
    before = store.bars_as_of(d("2026-01-15"), ["AAPL"], lookback=100)
    store.upsert_bars([bar("AAPL", "2026-02-01", 999.0)])
    after = store.bars_as_of(d("2026-01-15"), ["AAPL"], lookback=100)
    assert before == after


def test_planted_lookahead_bug_is_caught(store, monkeypatch):
    """Replace the read path with one that ignores `as_of`, and assert the
    invariant check above fails. If this test ever passes without the
    assertion firing, our lookahead detection is broken."""

    def leaky_bars_as_of(self, as_of, symbols, lookback):
        out = {}
        for symbol in symbols:
            cur = self._conn.execute(
                "SELECT * FROM bars WHERE symbol = ? ORDER BY date DESC LIMIT ?",
                (symbol, lookback),
            )
            found = [FeatureStore._to_bar(r) for r in cur.fetchall()]
            found.reverse()
            out[symbol] = found
        return out

    monkeypatch.setattr(FeatureStore, "bars_as_of", leaky_bars_as_of)

    as_of = d("2026-01-15")
    got = store.bars_as_of(as_of, ["AAPL"], lookback=100)
    leaked = [b.date for b in got["AAPL"] if b.date > as_of]
    assert leaked, "planted bug did not leak — the detection method is wrong"
```

- [ ] **Step 2: Run them**

Run: `.venv/bin/pytest tests/test_pointintime.py -v`
Expected: all 4 PASS immediately, because Task 3 implemented the guarantee correctly. That is the intended outcome — these tests exist as a regression net, and the planted-bug test proves the net has no hole.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pointintime.py
git commit -m "Add point-in-time invariant tests including planted lookahead bug"
```

---

### Task 5: Yahoo data ingest

**Files:**
- Create: `src/ghambla/store/ingest.py`, `tests/test_ingest.py`

**Interfaces:**
- Consumes: `Bar`, `FeatureStore` from Task 3
- Produces:
  - `parse_yahoo_chart(payload: dict, symbol: str) -> list[Bar]`
  - `YahooDataSource(pause_seconds: float = 0.5)` with `fetch(symbol: str, range_: str = "10y") -> list[Bar]`
  - `ingest(store: FeatureStore, source, symbols: Sequence[str], range_: str = "10y") -> int`

**Design note:** `parse_yahoo_chart` is a pure function over an already-decoded dict, so it is tested against a fixture with no network. Only `YahooDataSource.fetch` touches the network, and no test exercises it — network calls in a test suite make the suite flaky and slow.

Yahoo returns `null` for some OHLCV entries on halted or illiquid days. Those bars must be **skipped**, not zero-filled, because a zero close would look like a -100% return to the momentum signal.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ingest.py
import datetime as dt
from ghambla.store.ingest import parse_yahoo_chart

PAYLOAD = {
    "chart": {"result": [{
        "meta": {"symbol": "AAPL"},
        # 2026-01-05 and 2026-01-06 UTC midnight
        "timestamp": [1767571200, 1767657600, 1767744000],
        "indicators": {
            "quote": [{
                "open":   [10.0, 11.0, None],
                "high":   [10.5, 11.5, None],
                "low":     [9.5, 10.5, None],
                "close":  [10.2, 11.2, None],
                "volume": [1000, 2000, None],
            }],
            "adjclose": [{"adjclose": [10.1, 11.1, None]}],
        },
    }]}
}


def test_parses_bars():
    bars = parse_yahoo_chart(PAYLOAD, "AAPL")
    assert len(bars) == 2
    assert bars[0].symbol == "AAPL"
    assert bars[0].close == 10.2
    assert bars[0].adj_close == 10.1
    assert bars[0].volume == 1000


def test_bars_are_dates_not_datetimes():
    bars = parse_yahoo_chart(PAYLOAD, "AAPL")
    assert isinstance(bars[0].date, dt.date)
    assert not isinstance(bars[0].date, dt.datetime)


def test_null_bars_are_skipped_not_zero_filled():
    bars = parse_yahoo_chart(PAYLOAD, "AAPL")
    assert all(b.close > 0 for b in bars)
    assert len(bars) == 2  # the third row was all-null


def test_empty_result_yields_no_bars():
    assert parse_yahoo_chart({"chart": {"result": []}}, "AAPL") == []
```

- [ ] **Step 2: Run and watch them fail**

Run: `.venv/bin/pytest tests/test_ingest.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'ghambla.store.ingest'`

- [ ] **Step 3: Implement**

```python
# src/ghambla/store/ingest.py
"""Historical data ingest.

Phase 1 uses the Yahoo Finance chart endpoint: free, no key, ten years of
daily bars with adjusted closes. It is an unofficial endpoint, so it is
isolated behind `DataSource` and will be replaced by IBKR historical data in
Phase 3, when an account exists and the broker becomes the authoritative
source.
"""
import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from typing import Protocol, Sequence

from .store import Bar, FeatureStore

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
USER_AGENT = "Mozilla/5.0 (compatible; ghambla research)"


class DataSource(Protocol):
    def fetch(self, symbol: str, range_: str = "10y") -> list[Bar]: ...


def parse_yahoo_chart(payload: dict, symbol: str) -> list[Bar]:
    results = payload.get("chart", {}).get("result") or []
    if not results:
        return []
    r = results[0]
    stamps = r.get("timestamp") or []
    quote = (r.get("indicators", {}).get("quote") or [{}])[0]
    adj_block = (r.get("indicators", {}).get("adjclose") or [{}])[0]
    adj = adj_block.get("adjclose") or []

    bars: list[Bar] = []
    for i, ts in enumerate(stamps):
        row = [quote.get(k, [None] * len(stamps))[i] for k in ("open", "high", "low", "close", "volume")]
        adj_close = adj[i] if i < len(adj) else None
        if any(v is None for v in row) or adj_close is None:
            continue  # halted or illiquid day: skip, never zero-fill
        o, h, lo, c, v = row
        bars.append(Bar(
            symbol=symbol,
            date=dt.datetime.fromtimestamp(ts, dt.UTC).date(),
            open=float(o), high=float(h), low=float(lo), close=float(c),
            adj_close=float(adj_close), volume=int(v),
        ))
    return bars


class YahooDataSource:
    def __init__(self, pause_seconds: float = 0.5) -> None:
        self._pause = pause_seconds

    def fetch(self, symbol: str, range_: str = "10y") -> list[Bar]:
        params = urllib.parse.urlencode({"range": range_, "interval": "1d", "events": "div,split"})
        req = urllib.request.Request(f"{CHART_URL}{symbol}?{params}", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
        time.sleep(self._pause)  # be polite to an endpoint we do not pay for
        return parse_yahoo_chart(payload, symbol)


def ingest(store: FeatureStore, source: DataSource, symbols: Sequence[str], range_: str = "10y") -> int:
    total = 0
    for symbol in symbols:
        bars = source.fetch(symbol, range_)
        total += store.upsert_bars(bars)
    return total
```

- [ ] **Step 4: Run and watch them pass**

Run: `.venv/bin/pytest tests/test_ingest.py -v` → 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/ghambla/store/ingest.py tests/test_ingest.py
git commit -m "Add Yahoo historical data ingest with null-bar skipping"
```

---

### Task 6: Signal interface and 12-1 momentum

**Files:**
- Create: `src/ghambla/signals/__init__.py`, `src/ghambla/signals/base.py`, `src/ghambla/signals/momentum.py`, `tests/test_momentum.py`

**Interfaces:**
- Consumes: `FeatureStore`, `Bar` from Task 3
- Produces:
  - `Score` frozen dataclass: `value: float, confidence: float, rationale: str`
  - `Signal` Protocol with `name: str` and `score(store, as_of, universe) -> dict[str, Score]`
  - `MomentumSignal(lookback_days: int = 252, skip_days: int = 21)`, `name = "momentum_12_1"`

**Why 12-1:** classic cross-sectional momentum — total return over the last twelve months, *excluding* the most recent month, because the skipped month carries short-term reversal that works against you. Deliberately boring: the point of Phase 1 is to validate the harness, not to find alpha.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_momentum.py
import datetime as dt
import pytest
from ghambla.signals.momentum import MomentumSignal
from ghambla.store.store import Bar, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "mom.db")
    yield s
    s.close()


def make_series(store, symbol, start_price, daily_growth, n=300, start="2025-01-01"):
    day = d(start)
    price = start_price
    bars = []
    for _ in range(n):
        bars.append(Bar(symbol=symbol, date=day, open=price, high=price, low=price,
                        close=price, adj_close=price, volume=1000))
        price *= daily_growth
        day += dt.timedelta(days=1)
    store.upsert_bars(bars)
    return day - dt.timedelta(days=1)


def test_riser_scores_above_faller(store):
    last = make_series(store, "UP", 100.0, 1.002)
    make_series(store, "DOWN", 100.0, 0.998)
    scores = MomentumSignal().score(store, last, ["UP", "DOWN"])
    assert scores["UP"].value > scores["DOWN"].value


def test_flat_series_scores_near_zero(store):
    last = make_series(store, "FLAT", 100.0, 1.0)
    scores = MomentumSignal().score(store, last, ["FLAT"])
    assert scores["FLAT"].value == pytest.approx(0.0, abs=1e-9)


def test_insufficient_history_yields_zero_confidence(store):
    last = make_series(store, "SHORT", 100.0, 1.002, n=30)
    scores = MomentumSignal().score(store, last, ["SHORT"])
    assert scores["SHORT"].confidence == 0.0
    assert scores["SHORT"].value == 0.0


def test_unknown_symbol_yields_zero_confidence(store):
    make_series(store, "UP", 100.0, 1.002)
    scores = MomentumSignal().score(store, d("2025-06-01"), ["NOPE"])
    assert scores["NOPE"].confidence == 0.0


def test_skips_the_most_recent_month(store):
    """A stock that rose all year then crashed in the final month should still
    score positively, because the last `skip_days` are excluded."""
    day = d("2025-01-01")
    price = 100.0
    bars = []
    for i in range(300):
        price = price * 1.004 if i < 279 else price * 0.97
        bars.append(Bar(symbol="SPIKE", date=day, open=price, high=price, low=price,
                        close=price, adj_close=price, volume=1000))
        day += dt.timedelta(days=1)
    store.upsert_bars(bars)
    scores = MomentumSignal().score(store, day - dt.timedelta(days=1), ["SPIKE"])
    assert scores["SPIKE"].value > 0


def test_rationale_is_populated(store):
    last = make_series(store, "UP", 100.0, 1.002)
    scores = MomentumSignal().score(store, last, ["UP"])
    assert "momentum" in scores["UP"].rationale.lower()
```

- [ ] **Step 2: Run and watch them fail**

Run: `.venv/bin/pytest tests/test_momentum.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'ghambla.signals'`

- [ ] **Step 3: Implement the base types**

```python
# src/ghambla/signals/base.py
import datetime as dt
from dataclasses import dataclass
from typing import Protocol, Sequence

from ..store.store import FeatureStore


@dataclass(frozen=True)
class Score:
    """One signal's opinion about one symbol at one point in time.

    `value` is comparable across symbols within a single signal, not across
    signals. `confidence` is 0.0 when the signal has no opinion — missing
    history, a failed API call — and the allocator must treat it as abstention
    rather than as a bearish view.
    """
    value: float
    confidence: float
    rationale: str


NO_OPINION = Score(value=0.0, confidence=0.0, rationale="insufficient data")


class Signal(Protocol):
    name: str

    def score(self, store: FeatureStore, as_of: dt.date,
              universe: Sequence[str]) -> dict[str, Score]: ...
```

- [ ] **Step 4: Implement momentum**

```python
# src/ghambla/signals/momentum.py
"""Cross-sectional 12-1 momentum.

Total return over the last `lookback_days`, excluding the most recent
`skip_days`. The skipped month is standard practice: short-term reversal in
the latest month works against momentum.

Deliberately simple. Phase 1 exists to validate the measurement harness, not
to find an edge.
"""
import datetime as dt
from typing import Sequence

from ..store.store import FeatureStore
from .base import NO_OPINION, Score


class MomentumSignal:
    name = "momentum_12_1"

    def __init__(self, lookback_days: int = 252, skip_days: int = 21) -> None:
        if skip_days >= lookback_days:
            raise ValueError("skip_days must be smaller than lookback_days")
        self.lookback_days = lookback_days
        self.skip_days = skip_days

    def score(self, store: FeatureStore, as_of: dt.date,
              universe: Sequence[str]) -> dict[str, Score]:
        history = store.bars_as_of(as_of, universe, lookback=self.lookback_days)
        out: dict[str, Score] = {}
        for symbol in universe:
            bars = history.get(symbol, [])
            if len(bars) < self.lookback_days:
                out[symbol] = NO_OPINION
                continue
            start = bars[0].adj_close
            end = bars[-1 - self.skip_days].adj_close
            if start <= 0:
                out[symbol] = NO_OPINION
                continue
            value = (end / start) - 1.0
            out[symbol] = Score(
                value=value,
                confidence=1.0,
                rationale=(f"12-1 momentum {value:+.1%} over {self.lookback_days}d "
                           f"excluding last {self.skip_days}d"),
            )
        return out
```

Also create an empty `src/ghambla/signals/__init__.py`.

- [ ] **Step 5: Run and watch them pass**

Run: `.venv/bin/pytest tests/test_momentum.py -v` → 6 passed

- [ ] **Step 6: Commit**

```bash
git add src/ghambla/signals tests/test_momentum.py
git commit -m "Add signal protocol and 12-1 momentum signal"
```

---

### Task 7: Portfolio construction

**Files:**
- Create: `src/ghambla/portfolio.py`, `tests/test_portfolio.py`

**Interfaces:**
- Consumes: `Score` from Task 6
- Produces:
  - `Target` frozen dataclass: `symbol: str, weight: float`
  - `equal_weight_top_n(scores: dict[str, Score], n: int) -> list[Target]`

Signals with `confidence == 0.0` are excluded before ranking — abstention is not a bearish view. Only positive-value scores are held, because Phase 1 is long-only (no shorting, per the design doc's out-of-scope list).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_portfolio.py
import pytest
from ghambla.portfolio import Target, equal_weight_top_n
from ghambla.signals.base import Score


def s(v, conf=1.0):
    return Score(value=v, confidence=conf, rationale="test")


def test_picks_top_n_by_value():
    scores = {"A": s(0.5), "B": s(0.1), "C": s(0.9), "D": s(0.3)}
    targets = equal_weight_top_n(scores, n=2)
    assert [t.symbol for t in targets] == ["C", "A"]


def test_weights_are_equal_and_sum_to_one():
    scores = {"A": s(0.5), "B": s(0.4), "C": s(0.3), "D": s(0.2)}
    targets = equal_weight_top_n(scores, n=4)
    assert all(t.weight == pytest.approx(0.25) for t in targets)
    assert sum(t.weight for t in targets) == pytest.approx(1.0)


def test_zero_confidence_scores_are_excluded():
    scores = {"A": s(0.9, conf=0.0), "B": s(0.5), "C": s(0.4)}
    targets = equal_weight_top_n(scores, n=3)
    assert [t.symbol for t in targets] == ["B", "C"]


def test_negative_momentum_is_not_held_long_only():
    scores = {"A": s(-0.5), "B": s(0.2), "C": s(-0.1)}
    targets = equal_weight_top_n(scores, n=3)
    assert [t.symbol for t in targets] == ["B"]
    assert targets[0].weight == pytest.approx(1.0)


def test_no_eligible_symbols_yields_no_targets():
    assert equal_weight_top_n({"A": s(-0.5), "B": s(-0.2)}, n=3) == []


def test_fewer_eligible_than_n_still_sums_to_one():
    targets = equal_weight_top_n({"A": s(0.5), "B": s(0.2)}, n=5)
    assert sum(t.weight for t in targets) == pytest.approx(1.0)
```

- [ ] **Step 2: Run and watch them fail**

Run: `.venv/bin/pytest tests/test_portfolio.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'ghambla.portfolio'`

- [ ] **Step 3: Implement**

```python
# src/ghambla/portfolio.py
"""Turn signal scores into target portfolio weights.

Phase 1 is long-only and equal-weight. Volatility scaling and per-name caps
arrive in Phase 2 alongside the risk gate.
"""
from dataclasses import dataclass

from .signals.base import Score


@dataclass(frozen=True)
class Target:
    symbol: str
    weight: float


def equal_weight_top_n(scores: dict[str, Score], n: int) -> list[Target]:
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")

    eligible = [(sym, sc) for sym, sc in scores.items() if sc.confidence > 0.0 and sc.value > 0.0]
    eligible.sort(key=lambda pair: (-pair[1].value, pair[0]))
    chosen = eligible[:n]
    if not chosen:
        return []

    weight = 1.0 / len(chosen)
    return [Target(symbol=sym, weight=weight) for sym, _ in chosen]
```

- [ ] **Step 4: Run and watch them pass**

Run: `.venv/bin/pytest tests/test_portfolio.py -v` → 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/ghambla/portfolio.py tests/test_portfolio.py
git commit -m "Add long-only equal-weight portfolio construction"
```

---

### Task 8: Backtest engine with next-open fills

**Files:**
- Create: `src/ghambla/backtest.py`, `tests/test_backtest.py`

**Interfaces:**
- Consumes: `FeatureStore` (Task 3), `ibkr_tiered_commission` (Task 2), `Signal` (Task 6), `equal_weight_top_n` (Task 7)
- Produces:
  - `Trade` frozen dataclass: `date: dt.date, symbol: str, side: str, shares: float, price: float, commission: float`
  - `BacktestResult` frozen dataclass: `dates: list[dt.date], equity: list[float], trades: list[Trade]`
  - `run_backtest(store, signal, start, end, initial_cash=10_000.0, top_n=10, rebalance_every=21, spread_bps=5.0) -> BacktestResult`

**The rule that matters:** a decision made on the close of bar D is executed at the **open of bar D+1**. Filling at D's close would use a price that did not exist when the decision was made, and is the most common source of fake backtest returns.

Slippage: buys fill at `open * (1 + spread_bps/20000)`, sells at `open * (1 - spread_bps/20000)` — half the spread each way.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backtest.py
import datetime as dt
import pytest
from ghambla.backtest import run_backtest
from ghambla.signals.base import Score
from ghambla.store.store import Bar, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


class AlwaysBuy:
    """Signal stub that always favours the first symbol in the universe."""
    name = "always_buy"

    def __init__(self, symbol="AAA"):
        self.symbol = symbol

    def score(self, store, as_of, universe):
        return {s: Score(value=1.0 if s == self.symbol else -1.0,
                         confidence=1.0, rationale="stub") for s in universe}


class NeverBuy:
    name = "never_buy"

    def score(self, store, as_of, universe):
        return {s: Score(value=-1.0, confidence=1.0, rationale="stub") for s in universe}


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "bt.db")
    day = d("2026-01-01")
    bars = []
    for i in range(60):
        # open is deliberately different from the prior close so a
        # close-filling bug produces a visibly different equity curve
        bars.append(Bar(symbol="AAA", date=day, open=100.0 + i, high=110.0 + i,
                        low=90.0 + i, close=105.0 + i, adj_close=105.0 + i, volume=10_000))
        day += dt.timedelta(days=1)
    s.upsert_bars(bars)
    s.set_universe(d("2025-12-01"), ["AAA"])
    yield s
    s.close()


def test_no_trades_when_signal_never_buys(store):
    r = run_backtest(store, NeverBuy(), d("2026-01-01"), d("2026-02-28"), initial_cash=10_000.0)
    assert r.trades == []
    assert r.equity[-1] == pytest.approx(10_000.0)


def test_fills_at_next_bar_open_not_signal_bar_close(store):
    r = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0, rebalance_every=1000, spread_bps=0.0)
    first = r.trades[0]
    # Decision is taken on the first date with enough data; the fill price must
    # equal that date's *successor* open, never the decision date's close.
    bars = store.bars_as_of(first.date, ["AAA"], lookback=1)["AAA"]
    decision_close = bars[-1].close
    assert first.price != pytest.approx(decision_close)
    following = store.trading_dates(first.date + dt.timedelta(days=1), d("2026-12-31"))
    nxt = store.bars_as_of(following[0], ["AAA"], lookback=1)["AAA"][-1]
    assert first.price == pytest.approx(nxt.open)


def test_commission_is_charged_on_every_trade(store):
    r = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"), initial_cash=10_000.0)
    assert all(t.commission > 0 for t in r.trades)


def test_equity_curve_has_one_point_per_trading_day(store):
    r = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"), initial_cash=10_000.0)
    expected = store.trading_dates(d("2026-01-01"), d("2026-02-28"))
    assert len(r.equity) == len(expected)
    assert r.dates == expected


def test_cash_never_goes_negative(store):
    r = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0, rebalance_every=1)
    assert all(e >= 0 for e in r.equity)


def test_spread_makes_buys_more_expensive_than_the_open(store):
    r = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0, rebalance_every=1000, spread_bps=100.0)
    first = r.trades[0]
    following = store.trading_dates(first.date + dt.timedelta(days=1), d("2026-12-31"))
    nxt = store.bars_as_of(following[0], ["AAA"], lookback=1)["AAA"][-1]
    assert first.price > nxt.open
```

- [ ] **Step 2: Run and watch them fail**

Run: `.venv/bin/pytest tests/test_backtest.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'ghambla.backtest'`

- [ ] **Step 3: Implement**

```python
# src/ghambla/backtest.py
"""Backtest engine.

The one rule that makes this trustworthy: a decision taken on the close of
bar D executes at the OPEN of bar D+1. Filling at D's close would use a price
that did not exist when the decision was made. That single mistake is the most
common source of backtests that look profitable and are not.
"""
import datetime as dt
from dataclasses import dataclass, field
from typing import Sequence

from .costs import ibkr_tiered_commission
from .portfolio import equal_weight_top_n
from .store.store import FeatureStore


@dataclass(frozen=True)
class Trade:
    date: dt.date
    symbol: str
    side: str  # "BUY" or "SELL"
    shares: float
    price: float
    commission: float


@dataclass(frozen=True)
class BacktestResult:
    dates: list[dt.date] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)


def run_backtest(store: FeatureStore, signal, start: dt.date, end: dt.date,
                 initial_cash: float = 10_000.0, top_n: int = 10,
                 rebalance_every: int = 21, spread_bps: float = 5.0) -> BacktestResult:
    dates = store.trading_dates(start, end)
    if not dates:
        return BacktestResult()

    cash = initial_cash
    positions: dict[str, float] = {}
    trades: list[Trade] = []
    equity: list[float] = []
    pending: list[tuple[str, float]] | None = None  # targets decided yesterday
    half_spread = spread_bps / 20_000.0

    for i, today in enumerate(dates):
        universe = store.universe_as_of(today)
        closes = _closes_on(store, today, list(set(universe) | set(positions)))

        # 1. Execute yesterday's decision at TODAY's open.
        if pending is not None:
            opens = _opens_on(store, today, list(set(universe) | set(positions)))
            equity_now = cash + sum(sh * closes.get(sym, 0.0) for sym, sh in positions.items())
            targets = {sym: w for sym, w in pending}

            for sym in sorted(set(positions) | set(targets)):
                px = opens.get(sym)
                if px is None or px <= 0:
                    continue
                want_value = targets.get(sym, 0.0) * equity_now
                want_shares = want_value / px
                delta = want_shares - positions.get(sym, 0.0)
                if abs(delta * px) < 1.0:  # ignore dust
                    continue
                side = "BUY" if delta > 0 else "SELL"
                fill = px * (1 + half_spread) if delta > 0 else px * (1 - half_spread)
                commission = ibkr_tiered_commission(abs(delta), fill)
                cost = delta * fill + commission
                if cost > cash and delta > 0:
                    affordable = max(0.0, (cash - commission) / fill)
                    if affordable * fill < 1.0:
                        continue
                    delta = affordable
                    commission = ibkr_tiered_commission(abs(delta), fill)
                    cost = delta * fill + commission
                cash -= cost
                positions[sym] = positions.get(sym, 0.0) + delta
                if abs(positions[sym]) < 1e-9:
                    del positions[sym]
                trades.append(Trade(date=today, symbol=sym, side=side, shares=abs(delta),
                                    price=fill, commission=commission))
            pending = None

        # 2. Mark to market on today's close.
        equity.append(cash + sum(sh * closes.get(sym, 0.0) for sym, sh in positions.items()))

        # 3. Decide, using only data knowable as of today's close.
        if i % rebalance_every == 0 and i < len(dates) - 1 and universe:
            scores = signal.score(store, today, universe)
            pending = [(t.symbol, t.weight) for t in equal_weight_top_n(scores, top_n)]

    return BacktestResult(dates=dates, equity=equity, trades=trades)


def _closes_on(store: FeatureStore, day: dt.date, symbols: Sequence[str]) -> dict[str, float]:
    out = {}
    for sym, bars in store.bars_as_of(day, symbols, lookback=1).items():
        if bars:
            out[sym] = bars[-1].close
    return out


def _opens_on(store: FeatureStore, day: dt.date, symbols: Sequence[str]) -> dict[str, float]:
    out = {}
    for sym, bars in store.bars_as_of(day, symbols, lookback=1).items():
        if bars and bars[-1].date == day:
            out[sym] = bars[-1].open
    return out
```

- [ ] **Step 4: Run and watch them pass**

Run: `.venv/bin/pytest tests/test_backtest.py -v` → 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/ghambla/backtest.py tests/test_backtest.py
git commit -m "Add backtest engine with next-open fills and spread costs"
```

---

### Task 9: Evaluation harness

**Files:**
- Create: `src/ghambla/evaluate.py`, `tests/test_evaluate.py`

**Interfaces:**
- Consumes: `BacktestResult` (Task 8), `FeatureStore` (Task 3)
- Produces:
  - `Metrics` frozen dataclass: `total_return: float, cagr: float, sharpe: float, max_drawdown: float, n_trades: int`
  - `compute_metrics(dates: list[dt.date], equity: list[float], n_trades: int) -> Metrics`
  - `buy_and_hold(store, symbol, start, end, initial_cash) -> BacktestResult`
  - `format_report(strategy: Metrics, benchmark: Metrics, benchmark_symbol: str) -> str`

Sharpe uses a zero risk-free rate and annualises by `sqrt(252)`. Stated in the docstring so nobody has to guess later.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_evaluate.py
import datetime as dt
import pytest
from ghambla.evaluate import compute_metrics, format_report


def days(n):
    return [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(n)]


def test_total_return_is_first_to_last():
    m = compute_metrics(days(3), [100.0, 110.0, 120.0], n_trades=2)
    assert m.total_return == pytest.approx(0.20)


def test_max_drawdown_measures_peak_to_trough():
    m = compute_metrics(days(5), [100.0, 120.0, 60.0, 80.0, 90.0], n_trades=0)
    assert m.max_drawdown == pytest.approx(-0.50)


def test_no_drawdown_on_a_monotonic_curve():
    m = compute_metrics(days(3), [100.0, 110.0, 120.0], n_trades=0)
    assert m.max_drawdown == pytest.approx(0.0)


def test_flat_curve_has_zero_sharpe_not_nan():
    m = compute_metrics(days(5), [100.0] * 5, n_trades=0)
    assert m.sharpe == 0.0


def test_single_point_curve_is_all_zeros():
    m = compute_metrics(days(1), [100.0], n_trades=0)
    assert m.total_return == 0.0
    assert m.sharpe == 0.0
    assert m.max_drawdown == 0.0


def test_empty_curve_is_all_zeros():
    m = compute_metrics([], [], n_trades=0)
    assert m.total_return == 0.0


def test_report_names_both_sides_and_the_verdict():
    strat = compute_metrics(days(3), [100.0, 105.0, 110.0], n_trades=4)
    bench = compute_metrics(days(3), [100.0, 102.0, 104.0], n_trades=1)
    text = format_report(strat, bench, "SPY")
    assert "SPY" in text
    assert "Sharpe" in text
    assert "Max drawdown" in text
```

- [ ] **Step 2: Run and watch them fail**

Run: `.venv/bin/pytest tests/test_evaluate.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'ghambla.evaluate'`

- [ ] **Step 3: Implement**

```python
# src/ghambla/evaluate.py
"""Performance metrics and honest benchmark comparison.

Sharpe assumes a zero risk-free rate and annualises daily returns by
sqrt(252). Drawdown is peak-to-trough on the equity curve, reported as a
negative fraction.

The benchmark comparison exists because "the strategy made money" is not a
result. Beating SPY buy-and-hold after costs is the only claim worth making,
and Gate 0 of the design doc requires it by a margin.
"""
import datetime as dt
import math
import statistics
from dataclasses import dataclass

from .backtest import BacktestResult, Trade
from .costs import ibkr_tiered_commission
from .store.store import FeatureStore

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class Metrics:
    total_return: float
    cagr: float
    sharpe: float
    max_drawdown: float
    n_trades: int


def compute_metrics(dates: list[dt.date], equity: list[float], n_trades: int) -> Metrics:
    if len(equity) < 2 or equity[0] <= 0:
        return Metrics(0.0, 0.0, 0.0, 0.0, n_trades)

    total_return = equity[-1] / equity[0] - 1.0

    span_days = max((dates[-1] - dates[0]).days, 1)
    years = span_days / 365.25
    cagr = (equity[-1] / equity[0]) ** (1 / years) - 1.0 if years > 0 else 0.0

    rets = [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity)) if equity[i - 1] > 0]
    if len(rets) < 2:
        sharpe = 0.0
    else:
        sd = statistics.stdev(rets)
        sharpe = 0.0 if sd == 0 else (statistics.fmean(rets) / sd) * math.sqrt(TRADING_DAYS_PER_YEAR)

    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            max_dd = min(max_dd, e / peak - 1.0)

    return Metrics(total_return=total_return, cagr=cagr, sharpe=sharpe,
                   max_drawdown=max_dd, n_trades=n_trades)


def buy_and_hold(store: FeatureStore, symbol: str, start: dt.date, end: dt.date,
                 initial_cash: float = 10_000.0) -> BacktestResult:
    """Benchmark: buy at the first available open, hold to the end."""
    dates = store.trading_dates(start, end)
    if not dates:
        return BacktestResult()

    first = store.bars_as_of(dates[0], [symbol], lookback=1)[symbol]
    if not first:
        return BacktestResult()
    entry = first[-1].open
    commission = ibkr_tiered_commission(initial_cash / entry, entry)
    shares = (initial_cash - commission) / entry

    equity, kept = [], []
    for day in dates:
        bars = store.bars_as_of(day, [symbol], lookback=1)[symbol]
        if bars:
            equity.append(shares * bars[-1].close)
            kept.append(day)

    trade = Trade(date=dates[0], symbol=symbol, side="BUY", shares=shares,
                  price=entry, commission=commission)
    return BacktestResult(dates=kept, equity=equity, trades=[trade])


def format_report(strategy: Metrics, benchmark: Metrics, benchmark_symbol: str) -> str:
    rows = [
        ("Total return", f"{strategy.total_return:+.2%}", f"{benchmark.total_return:+.2%}"),
        ("CAGR", f"{strategy.cagr:+.2%}", f"{benchmark.cagr:+.2%}"),
        ("Sharpe", f"{strategy.sharpe:.2f}", f"{benchmark.sharpe:.2f}"),
        ("Max drawdown", f"{strategy.max_drawdown:.2%}", f"{benchmark.max_drawdown:.2%}"),
        ("Trades", str(strategy.n_trades), str(benchmark.n_trades)),
    ]
    width = max(len(r[0]) for r in rows)
    lines = [f"{'Metric':<{width}}  {'Strategy':>12}  {benchmark_symbol:>12}",
             "-" * (width + 28)]
    lines += [f"{name:<{width}}  {a:>12}  {b:>12}" for name, a, b in rows]

    edge = strategy.sharpe - benchmark.sharpe
    lines.append("")
    lines.append(f"Sharpe edge over {benchmark_symbol}: {edge:+.2f}")
    if edge >= 0.3 and strategy.max_drawdown >= benchmark.max_drawdown:
        lines.append("Gate 0: PASS (Sharpe edge >= 0.30 and drawdown no worse than benchmark)")
    else:
        lines.append("Gate 0: FAIL — do not proceed to paper trading.")
    return "\n".join(lines)
```

- [ ] **Step 4: Run and watch them pass**

Run: `.venv/bin/pytest tests/test_evaluate.py -v` → 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/ghambla/evaluate.py tests/test_evaluate.py
git commit -m "Add evaluation harness with Gate 0 verdict"
```

---

### Task 10: CLI — ingest and backtest end to end

**Files:**
- Create: `src/ghambla/cli.py`, `src/ghambla/universe.py`

**Interfaces:**
- Consumes: everything above
- Produces: `python -m ghambla.cli ingest` and `python -m ghambla.cli backtest`

`universe.py` holds a hard-coded starter list of large-cap US symbols plus SPY. **This list is survivorship-biased** — it is today's large caps, not the large caps of ten years ago — and the module docstring must say so, because a backtest over it will look better than reality. Fixing it needs dated index membership, which is Phase 4 work.

- [ ] **Step 1: Write the universe module**

```python
# src/ghambla/universe.py
"""Starter universe for Phase 1.

WARNING: THIS LIST IS SURVIVORSHIP-BIASED. It is a snapshot of large-cap US
names as of 2026, so backtesting over a ten-year history implicitly assumes
we knew in 2016 which companies would still be large in 2026. Results will be
flattering and must not be treated as evidence of an edge.

Removing this bias requires dated index-membership data, which is Phase 4
work. Until then, the store's `set_universe(effective, symbols)` interface
already accepts dated snapshots, so no schema change will be needed.
"""

BENCHMARK = "SPY"

STARTER = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "LLY", "JPM",
    "V", "UNH", "XOM", "MA", "COST", "HD", "PG", "JNJ", "ABBV", "WMT",
    "MRK", "CVX", "KO", "PEP", "ADBE", "CRM", "BAC", "TMO", "MCD", "CSCO",
]
```

- [ ] **Step 2: Write the CLI**

```python
# src/ghambla/cli.py
"""Command line entry points.

    python -m ghambla.cli ingest
    python -m ghambla.cli backtest --start 2018-01-01 --end 2026-08-01
"""
import argparse
import datetime as dt
import sys

from .backtest import run_backtest
from .evaluate import buy_and_hold, compute_metrics, format_report
from .signals.momentum import MomentumSignal
from .store.ingest import YahooDataSource, ingest
from .store.store import FeatureStore
from .universe import BENCHMARK, STARTER

DEFAULT_DB = "data/market.db"


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def cmd_ingest(args) -> int:
    import pathlib
    pathlib.Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    store = FeatureStore(args.db)
    symbols = STARTER + [BENCHMARK]
    print(f"Ingesting {len(symbols)} symbols ({args.range}) into {args.db} ...")
    try:
        n = ingest(store, YahooDataSource(), symbols, args.range)
        store.set_universe(_date(args.universe_effective), STARTER)
        print(f"Stored {n} bars.")
    finally:
        store.close()
    return 0


def cmd_backtest(args) -> int:
    store = FeatureStore(args.db)
    try:
        dates = store.trading_dates(args.start, args.end)
        if not dates:
            print("No data in range. Run `ingest` first.", file=sys.stderr)
            return 1

        result = run_backtest(store, MomentumSignal(), args.start, args.end,
                              initial_cash=args.cash, top_n=args.top_n,
                              rebalance_every=args.rebalance_every)
        bench = buy_and_hold(store, BENCHMARK, args.start, args.end, initial_cash=args.cash)

        strat_m = compute_metrics(result.dates, result.equity, len(result.trades))
        bench_m = compute_metrics(bench.dates, bench.equity, len(bench.trades))
        print(f"\n{args.start} to {args.end}  |  {len(dates)} trading days\n")
        print(format_report(strat_m, bench_m, BENCHMARK))
        print("\nNOTE: the starter universe is survivorship-biased; see ghambla/universe.py")
    finally:
        store.close()
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ghambla")
    p.add_argument("--db", default=DEFAULT_DB)
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="download historical bars")
    pi.add_argument("--range", default="10y")
    pi.add_argument("--universe-effective", default="2016-01-01")
    pi.set_defaults(func=cmd_ingest)

    pb = sub.add_parser("backtest", help="run the momentum backtest")
    pb.add_argument("--start", type=_date, default=_date("2018-01-01"))
    pb.add_argument("--end", type=_date, default=dt.date.today())
    pb.add_argument("--cash", type=float, default=10_000.0)
    pb.add_argument("--top-n", type=int, default=10)
    pb.add_argument("--rebalance-every", type=int, default=21)
    pb.set_defaults(func=cmd_backtest)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: all tests pass.

- [ ] **Step 4: Ingest real data and run the backtest**

```bash
.venv/bin/python -m ghambla.cli ingest
.venv/bin/python -m ghambla.cli backtest --start 2018-01-01 --end 2026-08-01
```

Expected: a comparison table and a Gate 0 verdict. **A FAIL verdict here is a legitimate and likely outcome.** Report the real number; do not tune parameters until it passes, because that is curve-fitting and it is exactly what this harness exists to prevent.

- [ ] **Step 5: Commit**

```bash
git add src/ghambla/cli.py src/ghambla/universe.py
git commit -m "Add CLI for ingest and backtest with Gate 0 reporting"
```

---

## Self-Review

**Spec coverage.** Design doc §3.1 components covered by this plan: Feature Store (Task 3), Signal Generators (Task 6), Portfolio Constructor (Task 7), Execution Adapter `BacktestBroker` (Task 8), Evaluation Harness (Task 9). Deliberately deferred with their phase noted in the design doc: Allocator (Phase 5), Risk Gate and Journal (Phase 2), Reconciliation and paper/live adapters (Phase 3), news and fundamental signals (Phase 4). §8 testing categories 1 and 2 (point-in-time correctness, cost model) are Tasks 4 and 2; categories 3 and 4 (risk gate, reconciliation) belong to Phases 2 and 3 and have no Phase 1 task, correctly.

**Known gap, accepted for Phase 1:** the starter universe is survivorship-biased, which will flatter results. Task 10 requires this to be documented in code and printed on every backtest run so it cannot be forgotten.

**Type consistency.** `Bar`, `Score`, `Target`, `Trade`, `BacktestResult`, `Metrics` are each defined once and referenced with matching field names throughout. `bars_as_of(as_of, symbols, lookback)` keeps that signature in Tasks 3, 6, 8, 9. `ibkr_tiered_commission(shares, price)` keeps its signature in Tasks 2, 8, 9.
