"""Command line entry points.

    python -m ghambla.cli ingest --start 2018-01-01
    python -m ghambla.cli backtest --start 2018-01-01 --end 2026-08-01
"""
import argparse
import datetime as dt
import json
import pathlib
import sys

from .backtest import run_backtest
from .evaluate import buy_and_hold, compute_metrics, format_report
from .edgar import EdgarClient, fetch_fundamentals
from .signals.fundamental import FundamentalSignal
from .signals.momentum import MomentumSignal
from .sp500 import (
    ever_members_between,
    fetch_membership,
    members_on,
    snapshot_dates,
    to_yahoo_symbol,
)
from .store.ingest import YahooDataSource, YahooSplitSource, ingest, ingest_splits
from .store.store import FeatureStore
from .universe import BENCHMARK, WARMUP_DAYS

DEFAULT_DB = "data/market.db"
COVERAGE_PATH = "data/coverage.json"


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
                                  symbols, on_progress=progress)
        print(f"\nStored {n} split events. {len(failed)} lookups failed.")
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


def _signal(name):
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

        signal = _signal(args.signal)
        result = run_backtest(store, signal, args.start, args.end,
                              initial_cash=args.cash, top_n=args.top_n,
                              rebalance_every=args.rebalance_every)
        bench = buy_and_hold(store, BENCHMARK, args.start, args.end, initial_cash=args.cash)

        strat_m = compute_metrics(result.dates, result.equity, len(result.trades))
        bench_m = compute_metrics(bench.dates, bench.equity, len(bench.trades))

        first_universe = store.universe_as_of(dates[0])
        print(f"\n{args.start} to {args.end}  |  {len(dates)} trading days  "
              f"|  top {args.top_n}, rebalance every {args.rebalance_every}d")
        print(f"Signal: {signal.name}")
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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ghambla")
    p.add_argument("--db", default=DEFAULT_DB)
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="download membership and historical bars")
    pi.add_argument("--start", type=_date, default=_date("2018-01-01"))
    pi.add_argument("--end", type=_date, default=dt.date.today())
    pi.add_argument("--range", default="10y")
    pi.add_argument("--pause", type=float, default=0.2)
    pi.set_defaults(func=cmd_ingest)

    ps = sub.add_parser("ingest-splits", help="download split history")
    ps.add_argument("--start", type=_date, default=_date("2018-01-01"))
    ps.add_argument("--end", type=_date, default=dt.date.today())
    ps.add_argument("--pause", type=float, default=0.2)
    ps.set_defaults(func=cmd_ingest_splits)

    pf = sub.add_parser("ingest-fundamentals", help="download SEC annual fundamentals")
    pf.add_argument("--start", type=_date, default=_date("2018-01-01"))
    pf.add_argument("--end", type=_date, default=dt.date.today())
    pf.add_argument("--pause", type=float, default=0.12)
    pf.set_defaults(func=cmd_ingest_fundamentals)

    pb = sub.add_parser("backtest", help="run a backtest")
    pb.add_argument("--signal", choices=["momentum", "fundamental"], default="momentum")
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
