"""Command line entry points.

    python -m ghambla.cli ingest
    python -m ghambla.cli backtest --start 2018-01-01 --end 2026-08-01
"""
import argparse
import datetime as dt
import pathlib
import sys

from .backtest import run_backtest
from .evaluate import buy_and_hold, compute_metrics, format_report
from .signals.momentum import MomentumSignal
from .store.ingest import YahooDataSource, ingest
from .store.store import FeatureStore
from .universe import BENCHMARK, STARTER

DEFAULT_DB = "data/market.db"
BIAS_WARNING = ("NOTE: the starter universe is survivorship-biased, so these numbers "
                "flatter the strategy. See src/ghambla/universe.py.")


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def cmd_ingest(args) -> int:
    pathlib.Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    store = FeatureStore(args.db)
    symbols = STARTER + [BENCHMARK]
    print(f"Ingesting {len(symbols)} symbols ({args.range}) into {args.db} ...")
    try:
        n = ingest(store, YahooDataSource(), symbols, args.range)
        store.set_universe(args.universe_effective, STARTER)
        print(f"Stored {n} bars.")
    finally:
        store.close()
    return 0


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

        result = run_backtest(store, MomentumSignal(), args.start, args.end,
                              initial_cash=args.cash, top_n=args.top_n,
                              rebalance_every=args.rebalance_every)
        bench = buy_and_hold(store, BENCHMARK, args.start, args.end, initial_cash=args.cash)

        strat_m = compute_metrics(result.dates, result.equity, len(result.trades))
        bench_m = compute_metrics(bench.dates, bench.equity, len(bench.trades))

        print(f"\n{args.start} to {args.end}  |  {len(dates)} trading days  "
              f"|  top {args.top_n}, rebalance every {args.rebalance_every}d\n")
        print(format_report(strat_m, bench_m, BENCHMARK))
        print(f"\n{BIAS_WARNING}")
    finally:
        store.close()
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ghambla")
    p.add_argument("--db", default=DEFAULT_DB)
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="download historical bars")
    pi.add_argument("--range", default="10y")
    pi.add_argument("--universe-effective", type=_date, default=_date("2016-01-01"))
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
