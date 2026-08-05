import datetime as dt
from dataclasses import dataclass
from typing import Protocol, Sequence

from ..store.store import FeatureStore


@dataclass(frozen=True)
class Score:
    """One signal's opinion about one symbol at one point in time.

    `value` is comparable across symbols within a single signal, not across
    signals. `confidence` is 0.0 when the signal has no opinion — missing
    history, a failed API call — and consumers must treat that as abstention
    rather than as a bearish view.
    """
    value: float
    confidence: float
    rationale: str


NO_OPINION = Score(value=0.0, confidence=0.0, rationale="insufficient data")


class Signal(Protocol):
    name: str

    def score(self, store: FeatureStore, as_of: dt.date,
              universe: Sequence[str]) -> dict[str, Score]: ...
