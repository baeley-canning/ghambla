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


@dataclass(frozen=True)
class Fact:
    """One reported financial figure.

    `knowable_at` is the SEC filing date, not the period end. A quarter ending
    31 March is not knowable until the filing lands weeks later, and treating
    the period end as the knowable date is a classic lookahead bug.
    """
    symbol: str
    concept: str
    period_end: dt.date
    value: float
    knowable_at: dt.date
    accn: str


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

    def latest_bars_as_of(self, as_of: dt.date, symbols: Sequence[str]) -> dict[str, Bar]:
        """Most recent bar per symbol knowable at `as_of`, in a single query.

        The per-symbol loop in `bars_as_of` costs one query each, which at 500
        names across 2000 trading days is millions of round trips. The backtest
        needs only the latest bar on most days, so it gets it in one statement.
        Symbols with no bars are simply absent from the result.
        """
        if not symbols:
            return {}
        placeholders = ",".join("?" * len(symbols))
        cur = self._conn.execute(
            f"SELECT b.* FROM bars b JOIN ("
            f"  SELECT symbol, MAX(date) AS d FROM bars"
            f"  WHERE knowable_at <= ? AND symbol IN ({placeholders})"
            f"  GROUP BY symbol"
            f") m ON b.symbol = m.symbol AND b.date = m.d",
            (as_of.isoformat(), *symbols),
        )
        return {r["symbol"]: self._to_bar(r) for r in cur.fetchall()}

    def upsert_fundamentals(self, facts: Iterable["Fact"]) -> int:
        rows = [(f.symbol, f.concept, f.period_end.isoformat(), f.value,
                 f.knowable_at.isoformat(), f.accn) for f in facts]
        self._conn.executemany(
            "INSERT INTO fundamentals (symbol, concept, period_end, value, knowable_at, accn)"
            " VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(symbol, concept, period_end, accn) DO UPDATE SET"
            " value=excluded.value, knowable_at=excluded.knowable_at",
            rows,
        )
        self._conn.commit()
        return len(rows)

    def latest_fundamentals_as_of(self, as_of: dt.date, concept: str,
                                  symbols: Sequence[str]) -> dict[str, "Fact"]:
        """Most recently *filed* value of `concept` per symbol, as of a date.

        Ordered by filing date rather than period end: a restatement filed
        later supersedes, and a period that had not been reported yet is
        invisible. Ties on filing date break on the later period.
        """
        if not symbols:
            return {}
        placeholders = ",".join("?" * len(symbols))
        cur = self._conn.execute(
            f"SELECT f.* FROM fundamentals f JOIN ("
            f"  SELECT symbol, MAX(knowable_at || '|' || period_end) AS k"
            f"  FROM fundamentals"
            f"  WHERE concept = ? AND knowable_at <= ? AND symbol IN ({placeholders})"
            f"  GROUP BY symbol"
            f") m ON f.symbol = m.symbol"
            f"   AND f.knowable_at || '|' || f.period_end = m.k"
            f" WHERE f.concept = ?",
            (concept, as_of.isoformat(), *symbols, concept),
        )
        return {r["symbol"]: Fact(symbol=r["symbol"], concept=r["concept"],
                                  period_end=dt.date.fromisoformat(r["period_end"]),
                                  value=r["value"],
                                  knowable_at=dt.date.fromisoformat(r["knowable_at"]),
                                  accn=r["accn"])
                for r in cur.fetchall()}

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
