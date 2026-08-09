"""Command line entry points.

    python -m ghambla.cli ingest --start 2018-01-01
    python -m ghambla.cli backtest --start 2018-01-01 --end 2026-08-01
"""
import argparse
import datetime as dt
import json
import pathlib
import sys

from .backtest import WEIGHTINGS, run_backtest, signals_name
from .broker import SimulatedBroker
from .cycle import CASH_BUFFER, DailyCycle
from .journal import Journal
from .risk import RiskGate, RiskLimits
from .evaluate import buy_and_hold, compute_metrics, format_report
from .walkforward import format_walk_forward, run_walk_forward
from .edgar import EdgarClient, fetch_fundamentals
from .signals.fundamental import FundamentalSignal
from .signals.lowvol import LowVolSignal
from .signals.momentum import MomentumSignal
from .signals.reversal import ReversalSignal
from .signals.news import CachedClassifier, NewsSignal, StubClassifier
from .sp500 import (
    ever_members_between,
    fetch_membership,
    members_on,
    snapshot_dates,
    to_yahoo_symbol,
)
from .store.ingest import (
    YahooDataSource,
    YahooSplitSource,
    ingest,
    ingest_news,
    ingest_splits,
)
from .store.store import FeatureStore
from .universe import BENCHMARK, WARMUP_DAYS

DEFAULT_DB = "data/market.db"
COVERAGE_PATH = "data/coverage.json"
JOURNAL_PATH = "data/journal.jsonl"
SIM_STATE_PATH = "data/sim_account.json"


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def cmd_ingest(args) -> int:
    pathlib.Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    warmup_start = args.start - dt.timedelta(days=WARMUP_DAYS)

    print("Fetching S&P 500 membership history ...")
    spans = fetch_membership()
    tickers = ever_members_between(spans, warmup_start, args.end)
    symbols = sorted({to_yahoo_symbol(t) for t in tickers} | {BENCHMARK})
    print(f"{len(tickers)} tickers were index members between "
          f"{warmup_start} and {args.end}; downloading {len(symbols)} symbols.")

    store = FeatureStore(args.db)
    try:
        def progress(done, total, symbol):
            if done % 25 == 0 or done == total:
                print(f"  {done}/{total} ... {symbol}", flush=True)

        report = ingest(store, YahooDataSource(pause_seconds=args.pause),
                        symbols, args.range, on_progress=progress)

        print(f"\nStored {report.bars_stored} bars.")
        print(f"Coverage: {report.coverage:.1%} "
              f"({len(report.succeeded)} priced, {len(report.empty)} empty, "
              f"{len(report.failed)} failed)")

        print("Writing dated universe snapshots ...")
        snaps = snapshot_dates(warmup_start, args.end)
        for day in snaps:
            store.set_universe(day, sorted({to_yahoo_symbol(t) for t in members_on(spans, day)}))
        print(f"Wrote {len(snaps)} monthly snapshots.")

        pathlib.Path(COVERAGE_PATH).write_text(json.dumps({
            "generated": dt.date.today().isoformat(),
            "window": [warmup_start.isoformat(), args.end.isoformat()],
            "requested": report.requested,
            "priced": len(report.succeeded),
            "empty": sorted(report.empty),
            "failed": report.failed,
            "coverage": report.coverage,
        }, indent=2))
        print(f"Coverage detail written to {COVERAGE_PATH}")
    finally:
        store.close()
    return 0


def cmd_ingest_splits(args) -> int:
    if not pathlib.Path(args.db).exists():
        print(f"No database at {args.db}. Run `ingest` first.", file=sys.stderr)
        return 1
    store = FeatureStore(args.db)
    try:
        warmup_start = args.start - dt.timedelta(days=WARMUP_DAYS)
        spans = fetch_membership()
        symbols = sorted({to_yahoo_symbol(t)
                          for t in ever_members_between(spans, warmup_start, args.end)})
        print(f"Fetching split history for {len(symbols)} symbols ...")

        def progress(done, total, symbol):
            if done % 100 == 0 or done == total:
                print(f"  {done}/{total} ... {symbol}", flush=True)

        n, failed = ingest_splits(store, YahooSplitSource(pause_seconds=args.pause),
                                  symbols, range_=args.range, on_progress=progress)
        print(f"\nStored {n} split events. {len(failed)} lookups failed.")
    finally:
        store.close()
    return 0


def cmd_ingest_news(args) -> int:
    """Fetch news items for the dated universe (stub source by default)."""
    if not pathlib.Path(args.db).exists():
        print(f"No database at {args.db}. Run `ingest` first.", file=sys.stderr)
        return 1

    store = FeatureStore(args.db)
    try:
        warmup_start = args.start - dt.timedelta(days=WARMUP_DAYS)
        spans = fetch_membership()
        symbols = sorted({to_yahoo_symbol(t)
                          for t in ever_members_between(spans, warmup_start, args.end)})
        print(f"Fetching news for {len(symbols)} symbols ...")

        def progress(done, total, symbol):
            if done % 100 == 0 or done == total:
                print(f"  {done}/{total} ... {symbol}", flush=True)

        from .store.ingest import NewsSource
        from .store.store import NewsItem

        class StubNewsSource:
            """Canned news so the pipeline is exercisable without an API key."""

            def fetch(self, symbol: str) -> list[NewsItem]:
                return [
                    NewsItem(symbol=symbol,
                             published_at=dt.datetime.now(dt.UTC),
                             source="stub",
                             headline=f"{symbol} beats expectations",
                             body="revenue growth and profit beat estimates",
                             content_hash=f"stub-{symbol}",
                             knowable_at=dt.date.today()),
                ]

        n, failed = ingest_news(store, StubNewsSource(), symbols, on_progress=progress)
        print(f"\nStored {n} news items. {len(failed)} lookups failed.")
    finally:
        store.close()
    return 0


def cmd_ingest_fundamentals(args) -> int:
    if not pathlib.Path(args.db).exists():
        print(f"No database at {args.db}. Run `ingest` first.", file=sys.stderr)
        return 1

    store = FeatureStore(args.db)
    try:
        warmup_start = args.start - dt.timedelta(days=WARMUP_DAYS)
        spans = fetch_membership()
        symbols = sorted({to_yahoo_symbol(t)
                          for t in ever_members_between(spans, warmup_start, args.end)})
        print(f"Fetching SEC annual fundamentals for {len(symbols)} symbols ...")

        def progress(done, total, symbol):
            if done % 50 == 0 or done == total:
                print(f"  {done}/{total} ... {symbol}", flush=True)

        facts, failed = fetch_fundamentals(EdgarClient(pause_seconds=args.pause),
                                           symbols, on_progress=progress)
        stored = store.upsert_fundamentals(facts)
        with_data = len({f.symbol for f in facts})
        print(f"\nStored {stored} facts for {with_data}/{len(symbols)} symbols "
              f"({with_data / len(symbols):.1%} coverage).")
        print(f"{len(failed)} lookups failed (delisted or never SEC-registered).")
    finally:
        store.close()
    return 0


SIGNAL_NAMES = ["momentum", "fundamental", "news", "lowvol", "reversal"]


def _signals(names):
    return {n: _signal(n) for n in names}


def _signal(name):
    if name == "news":
        return NewsSignal(CachedClassifier(StubClassifier(), "data/news_cache.json"))
    if name == "lowvol":
        return LowVolSignal()
    if name == "reversal":
        return ReversalSignal()
    return {"momentum": MomentumSignal, "fundamental": FundamentalSignal}[name]()


def cmd_backtest(args) -> int:
    if not pathlib.Path(args.db).exists():
        print(f"No database at {args.db}. Run `ingest` first.", file=sys.stderr)
        return 1

    store = FeatureStore(args.db)
    try:
        dates = store.trading_dates(args.start, args.end)
        if not dates:
            print("No data in range. Run `ingest` first.", file=sys.stderr)
            return 1

        signals = _signals(args.signal)
        result = run_backtest(store, signals, args.start, args.end,
                              initial_cash=args.cash, top_n=args.top_n,
                              rebalance_every=args.rebalance_every,
                              spread_bps=args.spread_bps,
                              weighting=args.weighting,
                              regime_filter=args.regime_filter,
                              risk_gate=RiskGate() if (args.risk_gate or args.live_parity) else None,
                              cash_buffer=CASH_BUFFER if args.live_parity else 0.0)
        bench = buy_and_hold(store, BENCHMARK, args.start, args.end, initial_cash=args.cash)

        strat_m = compute_metrics(result.dates, result.equity, len(result.trades))
        bench_m = compute_metrics(bench.dates, bench.equity, len(bench.trades))

        first_universe = store.universe_as_of(dates[0])
        print(f"\n{args.start} to {args.end}  |  {len(dates)} trading days  "
              f"|  top {args.top_n}, rebalance every {args.rebalance_every}d")
        print(f"Signal: {signals_name(signals)}")
        print(f"Universe on day one: {len(first_universe)} names (dated S&P 500 membership)\n")
        print(format_report(strat_m, bench_m, BENCHMARK))

        cov = pathlib.Path(COVERAGE_PATH)
        if cov.exists():
            data = json.loads(cov.read_text())
            print(f"\nPrice coverage of historical members: {data['coverage']:.1%} "
                  f"({data['priced']}/{data['requested']}). Names we could not price "
                  f"were never buyable, so residual survivorship bias remains.")
    finally:
        store.close()
    return 0


def cmd_cycle(args) -> int:
    """Run one decision cycle against a broker."""
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
            print(f"Could not reach the broker at {getattr(broker, 'host', '?')}:"
                  f"{getattr(broker, 'port', '?')} — {exc}.\n"
                  f"IB Gateway or TWS must be running with the API enabled "
                  f"(paper Gateway 4002, live Gateway 4001, "
                  f"paper TWS 7497, live TWS 7496).", file=sys.stderr)
            return 1
        try:
            cycle = DailyCycle(
                store, _signals(args.signals), broker, journal,
                mode=args.broker if args.broker != "simulated" else "simulated",
                risk_gate=RiskGate(RiskLimits(max_position_weight=args.max_weight)),
                top_n=args.top_n)
            as_of = args.as_of or (store.trading_dates(
                args.as_of_floor, dt.date.today()) or [dt.date.today()])[-1]
            result = cycle.run(as_of, halt=args.halt)
        finally:
            broker.disconnect()

        print(f"\nCycle {result.as_of} via {broker.name}")
        print(f"  equity     {result.equity:,.2f}")
        print(f"  targets    {len(result.targets)}")
        print(f"  orders     {len(result.orders)}  fills {len(result.fills)}")
        if result.halted:
            print("  HALTED — no orders placed")
        for reason in result.reasons:
            print(f"    - {reason}")
        print(f"  journal    {journal.count()} records at {journal.path}")
    finally:
        store.close()
    return 0


def cmd_evaluate(args) -> int:
    """Walk-forward Gate 0 evaluation for a signal, with a held-out tail."""
    if not pathlib.Path(args.db).exists():
        print(f"No database at {args.db}. Run `ingest` first.", file=sys.stderr)
        return 1

    store = FeatureStore(args.db)
    try:
        signals = _signals(args.signal)
        dates = store.trading_dates(args.start, args.end)
        if not dates:
            print("No data in range. Run `ingest` first.", file=sys.stderr)
            return 1

        result = run_walk_forward(store, signals, args.start, args.end,
                                  n_windows=args.windows,
                                  holdout_frac=args.holdout,
                                  initial_cash=args.cash, top_n=args.top_n,
                                  rebalance_every=args.rebalance_every,
                                  spread_bps=args.spread_bps,
                              weighting=args.weighting,
                              regime_filter=args.regime_filter,
                              risk_gate=RiskGate() if (args.risk_gate or args.live_parity) else None,
                              cash_buffer=CASH_BUFFER if args.live_parity else 0.0)
        print(format_walk_forward(result))
        return 0
    finally:
        store.close()


def cmd_journal(args) -> int:
    journal = Journal(args.journal)
    rows = list(journal.read())
    if not rows:
        print("Journal is empty.")
        return 0
    print(f"{len(rows)} cycles in {journal.path}\n")
    for r in rows[-args.tail:]:
        held = ", ".join(f"{s}:{q:.2f}" for s, q in sorted(r["positions"].items())) or "flat"
        print(f"{r['as_of']}  {r['mode']:<10} equity {r['equity']:>12,.2f}  "
              f"orders {len(r['orders']):>2}  {held}")
        for v in r["risk_vetoes"]:
            print(f"    veto: {v}")
        for n in r.get("notes", []):
            print(f"    note: {n}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ghambla")
    p.add_argument("--db", default=DEFAULT_DB)
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="download membership and historical bars")
    pi.add_argument("--start", type=_date, default=_date("2018-01-01"))
    pi.add_argument("--end", type=_date, default=dt.date.today())
    pi.add_argument("--range", default="30y")
    pi.add_argument("--pause", type=float, default=0.2)
    pi.set_defaults(func=cmd_ingest)

    ps = sub.add_parser("ingest-splits", help="download split history")
    ps.add_argument("--start", type=_date, default=_date("2018-01-01"))
    ps.add_argument("--end", type=_date, default=dt.date.today())
    ps.add_argument("--range", default="30y")
    ps.add_argument("--pause", type=float, default=0.2)
    ps.set_defaults(func=cmd_ingest_splits)

    pf = sub.add_parser("ingest-fundamentals", help="download SEC annual fundamentals")
    pf.add_argument("--start", type=_date, default=_date("2018-01-01"))
    pf.add_argument("--end", type=_date, default=dt.date.today())
    pf.add_argument("--pause", type=float, default=0.12)
    pf.set_defaults(func=cmd_ingest_fundamentals)

    pn = sub.add_parser("ingest-news", help="download news items for the universe")
    pn.add_argument("--start", type=_date, default=_date("2018-01-01"))
    pn.add_argument("--end", type=_date, default=dt.date.today())
    pn.set_defaults(func=cmd_ingest_news)

    pb = sub.add_parser("backtest", help="run a backtest")
    pb.add_argument("--signal", nargs="+", choices=SIGNAL_NAMES, default=["momentum"],
                    help="one signal, or several combined by rank average")
    pb.add_argument("--start", type=_date, default=_date("2018-01-01"))
    pb.add_argument("--end", type=_date, default=dt.date.today())
    pb.add_argument("--cash", type=float, default=10_000.0)
    pb.add_argument("--top-n", type=int, default=10)
    pb.add_argument("--rebalance-every", type=int, default=21)
    pb.add_argument("--spread-bps", type=float, default=5.0,
                    help="modelled half-spread cost; raise it to test whether an "
                         "edge survives realistic execution")
    pb.add_argument("--weighting", choices=WEIGHTINGS, default="equal")
    pb.add_argument("--regime-filter", action="store_true",
                    help="hold cash while the benchmark is below its 200d average")
    pb.add_argument("--risk-gate", action="store_true",
                    help="apply the live risk gate, so Gate 0 measures what would run")
    pb.add_argument("--live-parity", action="store_true",
                    help="measure exactly what the live cycle runs: risk gate on, cash buffer on")
    pb.set_defaults(func=cmd_backtest)

    pe = sub.add_parser("evaluate", help="walk-forward Gate 0 evaluation")
    pe.add_argument("--signal", nargs="+", choices=SIGNAL_NAMES, default=["momentum"],
                    help="one signal, or several combined by rank average")
    pe.add_argument("--start", type=_date, default=_date("2018-01-01"))
    pe.add_argument("--end", type=_date, default=dt.date.today())
    pe.add_argument("--windows", type=int, default=4,
                    help="number of research windows before the holdout")
    pe.add_argument("--holdout", type=float, default=0.20,
                    help="fraction of the period held out untouched at the end")
    pe.add_argument("--cash", type=float, default=10_000.0)
    pe.add_argument("--top-n", type=int, default=10)
    pe.add_argument("--rebalance-every", type=int, default=21)
    pe.add_argument("--spread-bps", type=float, default=5.0,
                    help="modelled half-spread cost; raise it to test whether an "
                         "edge survives realistic execution")
    pe.add_argument("--weighting", choices=WEIGHTINGS, default="equal")
    pe.add_argument("--regime-filter", action="store_true",
                    help="hold cash while the benchmark is below its 200d average")
    pe.add_argument("--risk-gate", action="store_true",
                    help="apply the live risk gate, so Gate 0 measures what would run")
    pe.add_argument("--live-parity", action="store_true",
                    help="measure exactly what the live cycle runs: risk gate on, cash buffer on")
    pe.set_defaults(func=cmd_evaluate)

    pc = sub.add_parser("cycle", help="run one decision cycle against a broker")
    pc.add_argument("--broker", choices=["simulated", "ibkr"], default="simulated")
    pc.add_argument("--signals", nargs="+", choices=SIGNAL_NAMES,
                    default=["momentum", "fundamental"])
    pc.add_argument("--as-of", type=_date, default=None)
    pc.add_argument("--as-of-floor", type=_date, default=_date("2018-01-01"))
    pc.add_argument("--cash", type=float, default=10_000.0)
    pc.add_argument("--top-n", type=int, default=10)
    pc.add_argument("--max-weight", type=float, default=0.20)
    pc.add_argument("--journal", default=JOURNAL_PATH)
    pc.add_argument("--sim-state", default=SIM_STATE_PATH)
    pc.add_argument("--host", default="127.0.0.1")
    pc.add_argument("--port", type=int, default=None)
    pc.add_argument("--live", action="store_true",
                    help="use the live gateway port; the account you log in decides real money")
    pc.add_argument("--halt", action="store_true", help="kill switch: block all trading")
    pc.set_defaults(func=cmd_cycle)

    pj = sub.add_parser("journal", help="show recent decision cycles")
    pj.add_argument("--journal", default=JOURNAL_PATH)
    pj.add_argument("--tail", type=int, default=10)
    pj.set_defaults(func=cmd_journal)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
