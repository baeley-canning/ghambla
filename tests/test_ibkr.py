"""Tests for the IBKR adapter against a fake ib_async client.

These prove the translation logic, not the integration. Nothing here has
touched a real gateway — see the warning at the top of ghambla/ibkr.py.
"""
import pytest

from ghambla.broker import Order, OrderError
from ghambla.ibkr import IBKRBroker, LIVE_GATEWAY_PORT, PAPER_GATEWAY_PORT


class FakeContract:
    def __init__(self, symbol):
        self.symbol = symbol


class FakePosition:
    def __init__(self, symbol, position, avg_cost):
        self.contract = FakeContract(symbol)
        self.position = position
        self.avgCost = avg_cost


class FakeAccountValue:
    def __init__(self, tag, value, currency="USD"):
        self.tag = tag
        self.value = value
        self.currency = currency


class FakeStatus:
    def __init__(self, status="Filled", filled=0.0, avg=0.0):
        self.status = status
        self.filled = filled
        self.avgFillPrice = avg


class FakeFill:
    def __init__(self, commission):
        self.commission = commission


class FakeTrade:
    def __init__(self, status):
        self.orderStatus = status
        self.fills = []

    def isDone(self):
        return True


class FakeIB:
    def __init__(self, positions=(), cash=0.0, trade=None):
        self._positions = list(positions)
        self._cash = cash
        self._trade = trade
        self.connected_to = None
        self.placed = []
        self.disconnected = False

    def connect(self, host, port, clientId):
        self.connected_to = (host, port, clientId)

    def disconnect(self):
        self.disconnected = True

    def positions(self, account=None):
        return self._positions

    def accountValues(self, account=None):
        return [FakeAccountValue("NetLiquidation", "99999"),
                FakeAccountValue("TotalCashBalance", str(self._cash)),
                FakeAccountValue("TotalCashBalance", "123", currency="NZD")]

    def qualifyContracts(self, *contracts):
        return list(contracts)

    def placeOrder(self, contract, order):
        self.placed.append((contract, order))
        return self._trade

    def waitOnUpdate(self, timeout=None):
        return True


# --- connection ---

def test_paper_and_live_pick_different_ports():
    assert IBKRBroker(live=False).port == PAPER_GATEWAY_PORT
    assert IBKRBroker(live=True).port == LIVE_GATEWAY_PORT


def test_explicit_port_wins():
    assert IBKRBroker(port=7497).port == 7497


def test_connect_uses_the_detected_host_by_default():
    """Under WSL2 NAT, 127.0.0.1 does not reach IB Gateway on the Windows host.

    This test previously asserted 127.0.0.1, which encoded the bug: the adapter
    would have timed out against a gateway that was running fine, and the error
    would have read as "gateway down" rather than "wrong address".
    """
    from ghambla.ibkr import default_host
    ib = FakeIB()
    IBKRBroker(ib=ib, client_id=9).connect()
    assert ib.connected_to == (default_host(), PAPER_GATEWAY_PORT, 9)


def test_an_explicit_host_always_wins():
    ib = FakeIB()
    IBKRBroker(ib=ib, client_id=9, host="10.0.0.5").connect()
    assert ib.connected_to == ("10.0.0.5", PAPER_GATEWAY_PORT, 9)


def test_default_host_degrades_to_loopback_when_detection_fails(monkeypatch):
    """A wrong guess must fall back, never raise — an unreadable /proc file
    should not stop the adapter connecting at all."""
    import builtins

    import ghambla.ibkr as m

    def boom(*a, **k):
        raise OSError("unreadable")

    monkeypatch.setattr(builtins, "open", boom)
    assert m.default_host() == "127.0.0.1"


# --- snapshot ---

def test_snapshot_reads_positions_and_usd_cash():
    ib = FakeIB(positions=[FakePosition("AAPL", 10, 150.0)], cash=2500.0)
    snap = IBKRBroker(ib=ib).snapshot()
    assert snap.positions["AAPL"].shares == 10
    assert snap.positions["AAPL"].average_cost == 150.0
    assert snap.cash == 2500.0


def test_snapshot_ignores_non_usd_cash_rows():
    ib = FakeIB(positions=[], cash=2500.0)
    assert IBKRBroker(ib=ib).snapshot().cash == 2500.0


def test_zero_size_positions_are_dropped():
    ib = FakeIB(positions=[FakePosition("AAPL", 0, 150.0)])
    assert IBKRBroker(ib=ib).snapshot().positions == {}


# --- orders ---

def test_a_filled_order_reports_price_and_commission():
    trade = FakeTrade(FakeStatus("Filled", filled=10.0, avg=101.5))
    trade.fills = [FakeFill(0.35)]
    fill = IBKRBroker(ib=FakeIB(trade=trade)).place(Order("AAPL", "BUY", 10), 100.0)
    assert fill.shares == 10.0
    assert fill.price == 101.5
    assert fill.commission == pytest.approx(0.35)


def test_a_partial_fill_reports_what_actually_filled():
    """Never the requested size. The next cycle re-plans from real positions
    rather than chasing the remainder."""
    trade = FakeTrade(FakeStatus("Filled", filled=4.0, avg=100.0))
    fill = IBKRBroker(ib=FakeIB(trade=trade)).place(Order("AAPL", "BUY", 10), 100.0)
    assert fill.shares == 4.0


def test_a_cancelled_order_raises_and_is_not_retried():
    trade = FakeTrade(FakeStatus("Cancelled", filled=0.0))
    with pytest.raises(OrderError, match="rejected"):
        IBKRBroker(ib=FakeIB(trade=trade)).place(Order("AAPL", "BUY", 10), 100.0)


def test_an_unfilled_order_raises():
    trade = FakeTrade(FakeStatus("Submitted", filled=0.0))
    with pytest.raises(OrderError, match="did not fill"):
        IBKRBroker(ib=FakeIB(trade=trade)).place(Order("AAPL", "BUY", 10), 100.0)


def test_non_positive_size_is_refused_before_reaching_the_broker():
    ib = FakeIB(trade=FakeTrade(FakeStatus()))
    with pytest.raises(OrderError, match="non-positive"):
        IBKRBroker(ib=ib).place(Order("AAPL", "BUY", 0), 100.0)
    assert ib.placed == []


def test_the_order_carries_the_right_symbol_and_side():
    trade = FakeTrade(FakeStatus("Filled", filled=3.0, avg=50.0))
    ib = FakeIB(trade=trade)
    IBKRBroker(ib=ib).place(Order("MSFT", "SELL", 3), 50.0)
    contract, order = ib.placed[0]
    assert contract.symbol == "MSFT"
    assert order.action == "SELL"
    assert order.totalQuantity == 3
