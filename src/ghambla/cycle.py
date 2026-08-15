"""The daily cycle — one run of the whole system.

Order matters and is not negotiable:

  1. Ask the broker what it actually holds.
  2. Reconcile that against what we believed. A break halts everything.
  3. Score signals on data knowable as of the close.
  4. Combine, size, and pass through the risk gate.
  5. Diff targets against reality to get orders, and place them.
  6. Journal the entire reasoning chain, whatever happened.

Step 6 runs even when earlier steps fail, because a cycle that halted without
recording why is indistinguishable from a cycle that never ran.

Believed state comes from the last journal entry rather than memory, so a
restart cannot silently forget positions. On the very first run there is
nothing to compare against, so the broker's own snapshot is adopted and that
fact is recorded.
"""
import datetime as dt
from dataclasses import dataclass, field

from .allocator import RankAllocator, combine_scores
from .backtest import WEIGHTINGS, weigh
from .broker import Broker, Order, OrderError
from .journal import DecisionRecord, Journal
from .reconcile import reconcile
from .regime import trend_filter
from .risk import RiskDecision, RiskGate, RiskState
from .store.store import FeatureStore
from .vol import TRADING_DAYS_PER_YEAR

MIN_TRADE_VALUE = 1.0

# Fraction of equity held back from the target weights. Sizing to exactly 100%
# invested guarantees the final buy is rejected, because commission has to come
# from somewhere and a fill can print slightly above the reference price. Two
# percent covers both without materially changing exposure.
CASH_BUFFER = 0.02


@dataclass
class CycleResult:
    as_of: dt.date
    halted: bool
    reasons: list[str] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)
    fills: list = field(default_factory=list)
    targets: dict[str, float] = field(default_factory=dict)
    equity: float = 0.0


class DailyCycle:
    def __init__(self, store: FeatureStore, signals: dict, broker: Broker,
                 journal: Journal, mode: str,
                 allocator: RankAllocator | None = None,
                 risk_gate: RiskGate | None = None,
                 top_n: int = 10, cash_buffer: float = CASH_BUFFER,
                 weighting: str = "equal",
                 regime_filter: bool = False,
                 regime_lookback: int = 200,
                 quote_source=None) -> None:
        # Validate eagerly so a bad weighting fails at construction, not
        # mid-trading-day when the cycle is already running.
        if weighting not in WEIGHTINGS:
            raise ValueError(f"unknown weighting scheme: {weighting}")
        self.store = store
        self.signals = signals
        self.broker = broker
        self.journal = journal
        self.mode = mode
        self.allocator = allocator or RankAllocator()
        self.risk_gate = risk_gate or RiskGate()
        self.top_n = top_n
        self.cash_buffer = cash_buffer
        self.weighting = weighting
        self.regime_filter = regime_filter
        self.regime_lookback = regime_lookback
        self.quote_source = quote_source

    def run(self, as_of: dt.date, halt: bool = False) -> CycleResult:
        started = dt.datetime.now(dt.UTC)
        notes: list[str] = []
        universe = self.store.universe_as_of(as_of)
        bars = self.store.latest_bars_as_of(as_of, universe)
        prices = {s: b.close for s, b in bars.items()}

        snapshot = self.broker.snapshot()
        actual_positions = {s: p.shares for s, p in snapshot.positions.items()}

        # --- reconcile against what we believed last time ---
        previous = self.journal.last()
        if previous is None:
            notes.append("first cycle: adopting broker state as the baseline")
            recon_ok, recon_breaks = True, []
        else:
            r = reconcile(previous.get("positions", {}), previous.get("cash", 0.0), snapshot)
            recon_ok, recon_breaks = r.ok, r.describe()

        equity = snapshot.equity(prices)
        previous_equity = previous.get("equity", equity) if previous else equity
        peak_equity = max(equity, previous.get("peak_equity", equity) if previous else equity)
        data_as_of = max(bars.values(), key=lambda b: b.date).date if bars else as_of

        # --- score and combine ---
        by_signal = {}
        for name, signal in self.signals.items():
            try:
                by_signal[name] = signal.score(self.store, as_of, universe)
            except Exception as exc:
                notes.append(f"signal {name} failed: {type(exc).__name__}: {exc}")
        combined = combine_scores(by_signal, self.allocator)
        wanted = {t.symbol: t.weight for t in weigh(
            combined, self.top_n, self.weighting, self.store, as_of,
            TRADING_DAYS_PER_YEAR)}

        # --- risk ---
        # `is not True`, not `is False`, because trend_filter returns None when
        # it cannot be evaluated and an unknown regime must fail closed —
        # treating "cannot tell" as "risk-on" would take full exposure precisely
        # when the data is missing.
        risk_on = trend_filter(self.store, as_of,
                               lookback=self.regime_lookback) \
            if self.regime_filter else None
        if self.regime_filter and risk_on is not True:
            risk_on = False
        state = RiskState(equity=equity, peak_equity=peak_equity,
                          previous_equity=previous_equity, data_as_of=data_as_of,
                          today=as_of, reconciled=recon_ok, halted=halt,
                          halt_reason="manual halt requested" if halt else "",
                          risk_on=risk_on)
        decision = self.risk_gate.evaluate(wanted, state)
        reasons = recon_breaks + decision.vetoes

        orders, fills = [], []
        if decision.allowed:
            investable = equity * (1.0 - self.cash_buffer)
            # Quotes are execution-only: they have no knowable_at and would
            # make backtests unreproducible, so they must never reach a signal.
            # Sizing and execution must use the same price or orders get
            # rejected (quote above close) or mis-sized (quote below close).
            execution_prices = dict(prices)
            if self.quote_source is not None:
                symbols = sorted(set(actual_positions) | set(decision.targets))
                try:
                    quotes = self.quote_source.quotes(symbols)
                    for symbol in symbols:
                        quote = quotes.get(symbol)
                        if quote is not None and quote.mid is not None:
                            execution_prices[symbol] = quote.mid
                        else:
                            notes.append(f"no live quote for {symbol}, using stored close")
                except Exception as exc:
                    notes.append(f"quote source failed: {type(exc).__name__}: {exc}")
                    execution_prices = prices
            orders = self._orders_for(decision, actual_positions, execution_prices, investable)
            for order in orders:
                price = execution_prices.get(order.symbol)
                if price is None:
                    notes.append(f"no price for {order.symbol}, skipped")
                    continue
                try:
                    fills.append(self.broker.place(order, price))
                except OrderError as exc:
                    notes.append(f"order rejected {order.symbol}: {exc}")

        after = self.broker.snapshot()
        final_positions = {s: p.shares for s, p in after.positions.items()}

        self.journal.append(DecisionRecord(
            as_of=as_of, cycle_started=started, mode=self.mode,
            universe_size=len(universe),
            signal_scores={n: {s: {"value": sc.value, "confidence": sc.confidence,
                                   "rationale": sc.rationale}
                               for s, sc in scores.items() if sc.confidence > 0}
                           for n, scores in by_signal.items()},
            allocator=self.allocator.name,
            targets=decision.targets,
            risk_vetoes=reasons,
            orders=[{"symbol": o.symbol, "side": o.side, "shares": o.shares} for o in orders],
            fills=[{"symbol": f.symbol, "side": f.side, "shares": f.shares,
                    "price": f.price, "commission": f.commission} for f in fills],
            equity=after.equity(prices), cash=after.cash,
            positions=final_positions, notes=notes,
        ))

        return CycleResult(as_of=as_of, halted=not decision.allowed, reasons=reasons,
                           orders=orders, fills=fills, targets=decision.targets,
                           equity=after.equity(prices))

    def _orders_for(self, decision: RiskDecision, held: dict[str, float],
                    prices: dict[str, float], investable: float) -> list[Order]:
        orders: list[Order] = []
        for symbol in sorted(set(held) | set(decision.targets)):
            price = prices.get(symbol)
            if price is None or price <= 0:
                continue
            want_shares = decision.targets.get(symbol, 0.0) * investable / price
            delta = want_shares - held.get(symbol, 0.0)
            if abs(delta * price) < MIN_TRADE_VALUE:
                continue
            orders.append(Order(symbol=symbol,
                                side="BUY" if delta > 0 else "SELL",
                                shares=abs(delta)))
        # Sells first so their proceeds are available to fund the buys.
        return sorted(orders, key=lambda o: (o.side != "SELL", o.symbol))
