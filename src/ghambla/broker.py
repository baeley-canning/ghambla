"""Broker abstraction and a simulated implementation.

One interface, three implementations: the backtest engine, a simulated paper
broker for offline rehearsal, and IBKR for real paper/live accounts. Any logic
that exists in only one of them is a bug waiting to happen, so order sizing,
risk checks and journalling all live above this line.

`Position` and `AccountSnapshot` are what reconciliation compares against.
"""
import datetime as dt
import json
import pathlib
from dataclasses import dataclass, field
from typing import Protocol

from .costs import ibkr_tiered_commission


class OrderError(RuntimeError):
    """Broker rejected an order. Never retried automatically."""


@dataclass(frozen=True)
class Order:
    symbol: str
    side: str          # "BUY" | "SELL"
    shares: float
    limit: float | None = None   # None means market order


@dataclass(frozen=True)
class Fill:
    symbol: str
    side: str
    shares: float
    price: float
    commission: float
    at: dt.datetime


@dataclass(frozen=True)
class Position:
    symbol: str
    shares: float
    average_cost: float


@dataclass(frozen=True)
class AccountSnapshot:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash + sum(p.shares * prices.get(s, p.average_cost)
                               for s, p in self.positions.items())


class Broker(Protocol):
    name: str

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def snapshot(self) -> AccountSnapshot: ...
    def place(self, order: Order, reference_price: float) -> Fill: ...


class SimulatedBroker:
    """In-memory broker for offline rehearsal of the live cycle.

    Fills immediately at the reference price plus half the spread, charging
    IBKR Tiered commission. It is not a market simulator — it exists so the
    daily cycle, risk gate, journal and reconciliation can be exercised end to
    end without a network connection or an IBKR account.
    """

    name = "simulated"

    def __init__(self, cash: float = 10_000.0, spread_bps: float = 5.0,
                 state_path: str | pathlib.Path | None = None) -> None:
        self._cash = cash
        self._positions: dict[str, Position] = {}
        self._half_spread = spread_bps / 20_000.0
        self._connected = False
        self._state_path = pathlib.Path(state_path) if state_path else None

    def connect(self) -> None:
        """Load persisted state if there is any.

        Without this a multi-day rehearsal starts flat every run, and
        reconciliation correctly halts on the second cycle because the journal
        remembers positions the broker has forgotten.
        """
        self._connected = True
        if self._state_path and self._state_path.exists():
            data = json.loads(self._state_path.read_text())
            self._cash = float(data["cash"])
            self._positions = {
                s: Position(s, float(p["shares"]), float(p["average_cost"]))
                for s, p in data.get("positions", {}).items()
            }

    def disconnect(self) -> None:
        self._connected = False
        self._save()

    def _save(self) -> None:
        if not self._state_path:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps({
            "cash": self._cash,
            "positions": {s: {"shares": p.shares, "average_cost": p.average_cost}
                          for s, p in self._positions.items()},
        }, indent=2, sort_keys=True))

    def snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(cash=self._cash, positions=dict(self._positions))

    def place(self, order: Order, reference_price: float) -> Fill:
        if not self._connected:
            raise OrderError("broker not connected")
        if order.shares <= 0:
            raise OrderError(f"non-positive order size {order.shares}")
        if reference_price <= 0:
            raise OrderError(f"unusable reference price {reference_price}")

        buying = order.side == "BUY"
        price = reference_price * (1 + self._half_spread if buying
                                   else 1 - self._half_spread)
        commission = ibkr_tiered_commission(order.shares, price)
        cost = order.shares * price + commission

        held = self._positions.get(order.symbol)
        if buying:
            if cost > self._cash:
                raise OrderError(f"insufficient cash: need {cost:.2f}, have {self._cash:.2f}")
            self._cash -= cost
            prior_shares = held.shares if held else 0.0
            prior_cost = held.average_cost * prior_shares if held else 0.0
            new_shares = prior_shares + order.shares
            self._positions[order.symbol] = Position(
                order.symbol, new_shares,
                (prior_cost + order.shares * price) / new_shares)
        else:
            if held is None or held.shares < order.shares - 1e-9:
                raise OrderError(f"cannot sell {order.shares} of {order.symbol}, "
                                 f"hold {held.shares if held else 0}")
            self._cash += order.shares * price - commission
            remaining = held.shares - order.shares
            if remaining <= 1e-9:
                del self._positions[order.symbol]
            else:
                self._positions[order.symbol] = Position(
                    order.symbol, remaining, held.average_cost)

        self._save()
        return Fill(symbol=order.symbol, side=order.side, shares=order.shares,
                    price=price, commission=commission, at=dt.datetime.now(dt.UTC))
