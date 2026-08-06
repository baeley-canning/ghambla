"""Append-only decision log.

Every cycle writes one record: what was known, what each signal said, what the
allocator did with it, what the risk gate allowed, what was ordered, and what
came back. Without this you cannot answer "why did it buy that" three weeks
later, and a system whose decisions cannot be reconstructed cannot be debugged
or trusted with money.

JSON Lines on disk: append-only, survives a crash mid-write without corrupting
earlier records, and readable with any tool.
"""
import datetime as dt
import json
import pathlib
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Iterator


@dataclass(frozen=True)
class DecisionRecord:
    """One cycle's complete reasoning."""
    as_of: dt.date
    cycle_started: dt.datetime
    mode: str                                   # "backtest" | "paper" | "live"
    universe_size: int
    signal_scores: dict[str, dict[str, Any]]    # signal name -> symbol -> score dict
    allocator: str
    targets: dict[str, float]                   # symbol -> target weight
    risk_vetoes: list[str]                      # human-readable veto reasons
    orders: list[dict[str, Any]]
    fills: list[dict[str, Any]]
    equity: float
    cash: float
    positions: dict[str, float]
    notes: list[str] = field(default_factory=list)


def _encode(obj: Any) -> Any:
    if isinstance(obj, (dt.datetime,)):
        return obj.isoformat()
    if isinstance(obj, dt.date):
        return obj.isoformat()
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    raise TypeError(f"cannot serialise {type(obj).__name__}")


class Journal:
    """Append-only JSONL writer/reader.

    Never rewrites or deletes. A corrupted tail line is skipped on read rather
    than raising, so a crash mid-append cannot make the whole history
    unreadable.
    """

    def __init__(self, path: str | pathlib.Path) -> None:
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: DecisionRecord) -> None:
        line = json.dumps(asdict(record), default=_encode, sort_keys=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()

    def read(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue  # truncated tail from an interrupted write

    def last(self) -> dict[str, Any] | None:
        found = None
        for record in self.read():
            found = record
        return found

    def count(self) -> int:
        return sum(1 for _ in self.read())
