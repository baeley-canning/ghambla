"""Point-in-time market data store.

A daily bar for date D becomes knowable at D's close, so `knowable_at = date`.
This is why a decision made "as of D" may use bar D, and why the backtest must
then fill at D+1's open.

Fundamentals in Phase 4 will set `knowable_at` to the report date rather than
the period end. The column exists now so that change needs no migration.
"""
import datetime as dt
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from . import schema


@dataclass(frozen=True)
class Bar:
    symbol: str
    date: dt.date
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int


class FeatureStore:
    """The only way to read market data.

    Every read takes an `as_of` date and can only return facts that were
    knowable on or before it.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        for ddl in schema.ALL:
            self._conn.execute(ddl)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def upsert_bars(self, bars: Iterable[Bar]) -> int:
        rows = [
            (b.symbol, b.date.isoformat(), b.open, b.high, b.low, b.close,
             b.adj_close, b.volume, b.date.isoformat())
            for b in bars
        ]
        self._conn.executemany(
            "INSERT INTO bars (symbol, date, open, high, low, close, adj_close, volume, knowable_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(symbol, date) DO UPDATE SET"
            " open=excluded.open, high=excluded.high, low=excluded.low,"
            " close=excluded.close, adj_close=excluded.adj_close, volume=excluded.volume",
            rows,
        )
        self._conn.commit()
        return len(rows)

    def bars_as_of(self, as_of: dt.date, symbols: Sequence[str], lookback: int) -> dict[str, list[Bar]]:
        """The most recent `lookback` bars per symbol that were knowable at `as_of`.

        Returned oldest-first so callers can index chronologically.
        """
        out: dict[str, list[Bar]] = {}
        for symbol in symbols:
            cur = self._conn.execute(
                "SELECT * FROM bars WHERE symbol = ? AND knowable_at <= ?"
                " ORDER BY date DESC LIMIT ?",
                (symbol, as_of.isoformat(), lookback),
            )
            found = [self._to_bar(r) for r in cur.fetchall()]
            found.reverse()
            out[symbol] = found
        return out

    def set_universe(self, effective: dt.date, symbols: Sequence[str]) -> None:
        self._conn.executemany(
            "INSERT OR REPLACE INTO universe (effective, symbol, knowable_at) VALUES (?,?,?)",
            [(effective.isoformat(), s, effective.isoformat()) for s in symbols],
        )
        self._conn.commit()

    def universe_as_of(self, as_of: dt.date) -> list[str]:
        cur = self._conn.execute(
            "SELECT symbol FROM universe WHERE effective = ("
            "  SELECT MAX(effective) FROM universe WHERE knowable_at <= ?"
            ") ORDER BY symbol",
            (as_of.isoformat(),),
        )
        return [r["symbol"] for r in cur.fetchall()]

    def trading_dates(self, start: dt.date, end: dt.date) -> list[dt.date]:
        cur = self._conn.execute(
            "SELECT DISTINCT date FROM bars WHERE date >= ? AND date <= ? ORDER BY date",
            (start.isoformat(), end.isoformat()),
        )
        return [dt.date.fromisoformat(r["date"]) for r in cur.fetchall()]

    @staticmethod
    def _to_bar(r: sqlite3.Row) -> Bar:
        return Bar(symbol=r["symbol"], date=dt.date.fromisoformat(r["date"]),
                   open=r["open"], high=r["high"], low=r["low"], close=r["close"],
                   adj_close=r["adj_close"], volume=r["volume"])
