"""Reconciliation — compare what we believe against what the broker reports.

Silent state drift is the failure mode that turns a small bug into a large
loss: the system thinks it holds 100 shares, actually holds 200, and keeps
sizing every subsequent order off the wrong number. Every cycle therefore ends
by checking its own beliefs against the broker's record, and any mismatch
halts trading until a human clears it.

Tolerances exist because floating point and fractional shares will never match
to the last bit. They are deliberately tight — tight enough that a single
missed fill trips them.
"""
from dataclasses import dataclass, field

from .broker import AccountSnapshot

SHARE_TOLERANCE = 1e-4
CASH_TOLERANCE = 0.01


@dataclass(frozen=True)
class Break:
    kind: str          # "shares" | "cash" | "unexpected" | "missing"
    symbol: str
    expected: float
    actual: float

    def describe(self) -> str:
        where = f" in {self.symbol}" if self.symbol else ""
        return (f"{self.kind} mismatch{where}: "
                f"expected {self.expected:.6g}, broker reports {self.actual:.6g}")


@dataclass(frozen=True)
class Reconciliation:
    breaks: list[Break] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.breaks

    def describe(self) -> list[str]:
        return [b.describe() for b in self.breaks]


def reconcile(expected_positions: dict[str, float], expected_cash: float,
              actual: AccountSnapshot,
              share_tolerance: float = SHARE_TOLERANCE,
              cash_tolerance: float = CASH_TOLERANCE) -> Reconciliation:
    """Compare believed state against a broker snapshot."""
    breaks: list[Break] = []

    expected = {s: q for s, q in expected_positions.items() if abs(q) > share_tolerance}
    reported = {s: p.shares for s, p in actual.positions.items()
                if abs(p.shares) > share_tolerance}

    for symbol in sorted(set(expected) | set(reported)):
        want = expected.get(symbol, 0.0)
        got = reported.get(symbol, 0.0)
        if abs(want - got) <= share_tolerance:
            continue
        if symbol not in expected:
            breaks.append(Break("unexpected", symbol, 0.0, got))
        elif symbol not in reported:
            breaks.append(Break("missing", symbol, want, 0.0))
        else:
            breaks.append(Break("shares", symbol, want, got))

    if abs(expected_cash - actual.cash) > cash_tolerance:
        breaks.append(Break("cash", "", expected_cash, actual.cash))

    return Reconciliation(breaks)
