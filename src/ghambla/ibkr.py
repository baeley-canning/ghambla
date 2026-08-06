"""Interactive Brokers adapter.

⚠️  UNVERIFIED AGAINST A REAL GATEWAY.

This module has unit tests against a fake `ib_async` client, which prove the
translation logic is right: that orders map to the correct contract and action,
that a rejection raises rather than being retried, that partial fills are
reported as what actually filled. It has never been run against IB Gateway,
because that needs an account, credentials and a running desktop process.

Treat it as a first draft until it has completed a full paper session. Gate 2
of the design doc exists precisely to force that before real money is involved.

Connection details: IB Gateway or TWS must be running with the API enabled.
Ports are 7497 for paper TWS, 7496 for live TWS, 4002 for paper Gateway, 4001
for live Gateway. The `live` flag here only picks the default port and prints a
warning — it is not a safety mechanism, and the account you log the gateway
into is what actually decides whether the money is real.
"""
import datetime as dt

from .broker import AccountSnapshot, Fill, Order, OrderError, Position

PAPER_GATEWAY_PORT = 4002
LIVE_GATEWAY_PORT = 4001
PAPER_TWS_PORT = 7497
LIVE_TWS_PORT = 7496

# IBKR reports these statuses when an order will never fill.
DEAD_STATUSES = {"Cancelled", "ApiCancelled", "Inactive"}


class IBKRBroker:
    """Thin translation layer over ib_async.

    Deliberately thin. Sizing, risk and journalling live above the broker
    interface so they are identical in backtest, simulation and live — anything
    implemented only here would be untested until the day it matters.
    """

    name = "ibkr"

    def __init__(self, host: str = "127.0.0.1", port: int | None = None,
                 client_id: int = 1, live: bool = False,
                 account: str = "", ib=None, fill_timeout: float = 60.0) -> None:
        self.host = host
        self.live = live
        self.port = port if port is not None else (
            LIVE_GATEWAY_PORT if live else PAPER_GATEWAY_PORT)
        self.client_id = client_id
        self.account = account
        self.fill_timeout = fill_timeout
        self._ib = ib  # injected for tests; created on connect otherwise

    # --- connection ---

    def connect(self) -> None:
        if self._ib is None:
            from ib_async import IB  # imported lazily so tests need no gateway
            self._ib = IB()
        self._ib.connect(self.host, self.port, clientId=self.client_id)

    def disconnect(self) -> None:
        if self._ib is not None:
            self._ib.disconnect()

    # --- state ---

    def snapshot(self) -> AccountSnapshot:
        """Positions and settled cash, straight from the broker.

        This is the authority. Anything we believe that disagrees with it is
        wrong by definition, which is what reconciliation acts on.
        """
        positions: dict[str, Position] = {}
        for p in self._ib.positions(self.account) if self.account else self._ib.positions():
            symbol = getattr(p.contract, "symbol", None)
            if symbol is None or not p.position:
                continue
            positions[symbol] = Position(symbol=symbol, shares=float(p.position),
                                         average_cost=float(p.avgCost or 0.0))

        cash = 0.0
        for row in self._ib.accountValues(self.account) if self.account else self._ib.accountValues():
            if row.tag == "TotalCashBalance" and row.currency == "USD":
                cash = float(row.value)
                break
        return AccountSnapshot(cash=cash, positions=positions)

    # --- trading ---

    def place(self, order: Order, reference_price: float) -> Fill:
        """Submit a market order and wait for it to finish.

        Returns what actually filled, which may be less than requested. The
        caller re-plans from real positions next cycle rather than chasing the
        remainder — chasing is how a system ends up fighting the market.
        """
        if order.shares <= 0:
            raise OrderError(f"non-positive order size {order.shares}")

        from ib_async import LimitOrder, MarketOrder, Stock

        contract = Stock(order.symbol, "SMART", "USD")
        self._ib.qualifyContracts(contract)

        if order.limit is not None:
            ib_order = LimitOrder(order.side, order.shares, order.limit)
        else:
            ib_order = MarketOrder(order.side, order.shares)

        trade = self._ib.placeOrder(contract, ib_order)
        deadline = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=self.fill_timeout)
        while not trade.isDone() and dt.datetime.now(dt.UTC) < deadline:
            self._ib.waitOnUpdate(timeout=1.0)

        status = getattr(trade.orderStatus, "status", "")
        filled = float(getattr(trade.orderStatus, "filled", 0.0) or 0.0)

        if status in DEAD_STATUSES and filled == 0:
            raise OrderError(f"{order.symbol} {order.side} rejected: {status}")
        if filled == 0:
            raise OrderError(f"{order.symbol} {order.side} did not fill within "
                             f"{self.fill_timeout}s (status {status})")

        avg = float(getattr(trade.orderStatus, "avgFillPrice", 0.0) or reference_price)
        commission = sum(float(getattr(f, "commission", 0.0) or 0.0)
                         for f in (getattr(trade, "fills", None) or []))

        return Fill(symbol=order.symbol, side=order.side, shares=filled,
                    price=avg, commission=commission, at=dt.datetime.now(dt.UTC))
