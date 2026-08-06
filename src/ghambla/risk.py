"""Risk gate — the veto layer.

The most important module in the repository, and the only one that can stop
the system doing something. Two rules govern it:

  1. It can only ever reduce or block. There is no path through this code that
     increases exposure, and a test asserts it.
  2. It fails closed. Anything it cannot evaluate — stale data, an unknown
     price, a failed reconciliation — blocks trading rather than waving it
     through.

Limits are hard numbers agreed in advance, not suggestions. A gate that can be
argued with during a drawdown is not a gate.
"""
import datetime as dt
from dataclasses import dataclass, field

HALT_FILE_REASON = "manual kill switch engaged"


@dataclass(frozen=True)
class RiskLimits:
    max_position_weight: float = 0.20      # no single name above 20% of equity
    max_gross_exposure: float = 1.00       # long-only, never levered
    max_daily_loss: float = 0.05           # halt after -5% in one day
    max_drawdown: float = 0.25             # halt after -25% from peak
    max_data_staleness_days: int = 4       # refuse to trade on old prices
    min_positions: int = 1
    max_positions: int = 30


@dataclass
class RiskState:
    """What the gate needs to know that a single day's targets cannot tell it."""
    equity: float
    peak_equity: float
    previous_equity: float
    data_as_of: dt.date
    today: dt.date
    reconciled: bool = True
    halted: bool = False
    halt_reason: str = ""


@dataclass(frozen=True)
class RiskDecision:
    targets: dict[str, float]
    vetoes: list[str] = field(default_factory=list)
    trading_blocked: bool = False

    @property
    def allowed(self) -> bool:
        return not self.trading_blocked


class RiskGate:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()

    def evaluate(self, targets: dict[str, float], state: RiskState) -> RiskDecision:
        """Return targets that are safe to act on, plus why anything was cut.

        Blocking returns empty targets, which means "hold what you have" — not
        "liquidate". Liquidating on bad data is itself a trade made on bad data.
        """
        vetoes: list[str] = []
        limits = self.limits

        # --- conditions that stop all trading ---
        if state.halted:
            return RiskDecision({}, [state.halt_reason or HALT_FILE_REASON], True)

        if not state.reconciled:
            return RiskDecision({}, ["positions do not reconcile with broker"], True)

        staleness = (state.today - state.data_as_of).days
        if staleness > limits.max_data_staleness_days:
            return RiskDecision(
                {}, [f"market data is {staleness} days old "
                     f"(limit {limits.max_data_staleness_days})"], True)

        if state.equity <= 0:
            return RiskDecision({}, ["equity is zero or negative"], True)

        if state.previous_equity > 0:
            daily = state.equity / state.previous_equity - 1.0
            if daily <= -limits.max_daily_loss:
                return RiskDecision(
                    {}, [f"daily loss {daily:.2%} breached limit "
                         f"-{limits.max_daily_loss:.0%}"], True)

        if state.peak_equity > 0:
            drawdown = state.equity / state.peak_equity - 1.0
            if drawdown <= -limits.max_drawdown:
                return RiskDecision(
                    {}, [f"drawdown {drawdown:.2%} breached limit "
                         f"-{limits.max_drawdown:.0%}"], True)

        # --- adjustments that only ever reduce ---
        safe = {s: w for s, w in targets.items() if w > 0}

        if len(safe) > limits.max_positions:
            keep = sorted(safe.items(), key=lambda kv: (-kv[1], kv[0]))[:limits.max_positions]
            vetoes.append(f"trimmed {len(safe)} targets to {limits.max_positions}")
            safe = dict(keep)

        if safe and len(safe) < limits.min_positions:
            return RiskDecision({}, [f"only {len(safe)} target(s), "
                                     f"minimum {limits.min_positions}"], True)

        capped = {}
        for sym, weight in safe.items():
            if weight > limits.max_position_weight:
                vetoes.append(f"{sym} capped {weight:.1%} -> "
                              f"{limits.max_position_weight:.1%}")
                capped[sym] = limits.max_position_weight
            else:
                capped[sym] = weight

        gross = sum(capped.values())
        if gross > limits.max_gross_exposure:
            scale = limits.max_gross_exposure / gross
            vetoes.append(f"gross exposure {gross:.1%} scaled down to "
                          f"{limits.max_gross_exposure:.0%}")
            capped = {s: w * scale for s, w in capped.items()}

        return RiskDecision(capped, vetoes, False)
