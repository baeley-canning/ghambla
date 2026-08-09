"""Unattended daily cycle scheduler.

Phase 3's "scheduler running the daily cycle unattended". This module runs the
daily cycle once per trading day, holding on failure rather than retrying and
hoping — the project's default response to anything unexpected is "stop and
tell the human". Every attempt is journalled, including failures, so a day that
halted is distinguishable from a day that never ran.

The scheduler itself is deliberately thin: it decides *when* to run and *what
to do if it fails*, and delegates the actual cycle to `DailyCycle`. A real
deployment wires this to a systemd timer or cron; a sample unit file is
provided in `deploy/`.
"""
import datetime as dt
import sys
from dataclasses import dataclass, field

from .broker import Broker
from .cycle import DailyCycle
from .journal import Journal
from .store.store import FeatureStore


@dataclass
class SchedulerResult:
    as_of: dt.date
    ran: bool = False
    halted: bool = False
    error: str = ""
    notes: list[str] = field(default_factory=list)


class DailyScheduler:
    """Runs the daily cycle on the most recent trading day, once.

    `run_once` is idempotent per date: if the journal already has a record for
    `as_of`, it is skipped. This makes the scheduler safe to run from cron
    multiple times a day without double-trading.
    """

    def __init__(self, store: FeatureStore, signals: dict, broker: Broker,
                 journal: Journal, mode: str, top_n: int = 10,
                 max_weight: float = 0.20) -> None:
        self.store = store
        self.signals = signals
        self.broker = broker
        self.journal = journal
        self.mode = mode
        self.top_n = top_n
        self.max_weight = max_weight

    def _already_ran(self, as_of: dt.date) -> bool:
        for record in self.journal.read():
            if record.get("as_of") == as_of.isoformat():
                return True
        return False

    def run_once(self, as_of: dt.date | None = None) -> SchedulerResult:
        """Run the cycle for `as_of` (default: the latest trading day)."""
        if as_of is None:
            dates = self.store.trading_dates(dt.date(2018, 1, 1), dt.date.today())
            if not dates:
                return SchedulerResult(as_of=dt.date.today(),
                                       error="no trading dates in store")
            as_of = dates[-1]

        if self._already_ran(as_of):
            return SchedulerResult(as_of=as_of, ran=False,
                                   notes=["already ran for this date; skipping"])

        from .risk import RiskGate, RiskLimits
        cycle = DailyCycle(self.store, self.signals, self.broker, self.journal,
                           mode=self.mode,
                           risk_gate=RiskGate(RiskLimits(max_position_weight=self.max_weight)),
                           top_n=self.top_n)
        try:
            result = cycle.run(as_of)
        except Exception as exc:
            return SchedulerResult(as_of=as_of, ran=True, halted=True,
                                   error=f"{type(exc).__name__}: {exc}")
        return SchedulerResult(as_of=as_of, ran=True, halted=result.halted,
                               notes=result.reasons)


def main(argv=None) -> int:
    """CLI entry: run the daily cycle once, unattended.

        python -m ghambla.scheduler --broker simulated
        python -m ghambla.scheduler --broker ibkr --live
    """
    import argparse
    import pathlib

    from .broker import SimulatedBroker
    from .cli import DEFAULT_DB, JOURNAL_PATH, SIGNAL_NAMES, SIM_STATE_PATH, _signals

    p = argparse.ArgumentParser(prog="ghambla-scheduler")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--broker", choices=["simulated", "ibkr"], default="simulated")
    p.add_argument("--signals", nargs="+", choices=SIGNAL_NAMES,
                   default=["momentum", "fundamental"])
    p.add_argument("--as-of", type=lambda s: dt.date.fromisoformat(s), default=None)
    p.add_argument("--cash", type=float, default=10_000.0)
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--max-weight", type=float, default=0.20)
    p.add_argument("--journal", default=JOURNAL_PATH)
    p.add_argument("--sim-state", default=SIM_STATE_PATH)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--live", action="store_true")
    args = p.parse_args(argv)

    if not pathlib.Path(args.db).exists():
        print(f"No database at {args.db}. Run `ingest` first.", file=sys.stderr)
        return 1

    store = FeatureStore(args.db)
    journal = Journal(args.journal)
    try:
        if args.broker == "simulated":
            broker = SimulatedBroker(cash=args.cash, state_path=args.sim_state)
        else:
            from .ibkr import IBKRBroker
            broker = IBKRBroker(host=args.host, port=args.port, live=args.live)
            if args.live:
                print("!! LIVE MODE: orders will use real money.", file=sys.stderr)

        try:
            broker.connect()
        except (ConnectionRefusedError, OSError, TimeoutError) as exc:
            print(f"Could not reach the broker: {exc}", file=sys.stderr)
            return 1

        try:
            scheduler = DailyScheduler(store, _signals(args.signals), broker,
                                       journal, mode=args.broker, top_n=args.top_n,
                                       max_weight=args.max_weight)
            result = scheduler.run_once(args.as_of)
        finally:
            broker.disconnect()

        print(f"Scheduler {result.as_of}: ran={result.ran} halted={result.halted}")
        for note in result.notes:
            print(f"  - {note}")
        if result.error:
            print(f"  ERROR: {result.error}", file=sys.stderr)
            return 1
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())