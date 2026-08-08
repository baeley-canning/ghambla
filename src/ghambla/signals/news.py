"""News + LLM signal.

The design doc's Phase 4 first item: an LLM classifies headlines and filings
for materiality and direction, and the result feeds the ensemble. Two rules
from the design doc govern this module:

  1. Responses are cached by content hash, so a backtest is deterministic and
     never re-bills the API for the same headline on every run.
  2. Any failure or timeout returns NO_OPINION with zero confidence. It never
     blocks the cycle and never defaults to a directional view.

The `Classifier` protocol is the seam: a real LLM client implements it, and
tests use a stub. The signal itself is a pure function over the store plus the
classifier, so it is backtest-reproducible.
"""
import datetime as dt
import hashlib
import json
import pathlib
from dataclasses import dataclass
from typing import Protocol, Sequence

from ..store.store import FeatureStore, NewsItem
from .base import NO_OPINION, Score

# A headline older than this is stale news, not information.
MAX_NEWS_AGE_DAYS = 7

# How many recent items per symbol the signal looks at.
LOOKBACK_ITEMS = 5


@dataclass(frozen=True)
class Classification:
    """One LLM verdict on one news item."""
    direction: float   # -1.0 bearish .. +1.0 bullish
    confidence: float  # 0.0 .. 1.0
    rationale: str


class Classifier(Protocol):
    """Classifies a news item's materiality and direction."""

    def classify(self, item: NewsItem) -> Classification: ...


class StubClassifier:
    """Deterministic keyword classifier — the offline default.

    This is not an edge. It exists so the news signal can be exercised end to
    end without an API key: the `Classifier` protocol is the seam where a real
    LLM client drops in, and `CachedClassifier` makes either one deterministic
    across backtest runs.
    """

    def classify(self, item: NewsItem) -> Classification:
        text = f"{item.headline} {item.body}".lower()
        positive = ("beat", "raise", "upgrade", "record", "growth", "profit",
                    "buyback", "dividend", "win", "surge", "jump")
        negative = ("miss", "cut", "downgrade", "loss", "lawsuit", "fraud",
                    "recall", "layoff", "plunge", "drop", "investigation")
        score = 0.0
        hits = 0
        for word in positive:
            if word in text:
                score += 1.0
                hits += 1
        for word in negative:
            if word in text:
                score -= 1.0
                hits += 1
        if hits == 0:
            return Classification(direction=0.0, confidence=0.0,
                                  rationale="no signal words")
        return Classification(direction=score / hits, confidence=0.5,
                              rationale=f"{hits} signal word(s)")


class CachedClassifier:
    """Wraps a real classifier with a content-hash cache on disk.

    The cache key is the SHA-256 of the item's text (headline + body + source).
    A backtest that re-reads the same news items therefore pays for each
    classification once, and is deterministic across runs.
    """

    def __init__(self, inner: Classifier, cache_path: str | pathlib.Path) -> None:
        self._inner = inner
        self._path = pathlib.Path(cache_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Classification] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for key, row in data.items():
            self._cache[key] = Classification(
                direction=float(row["direction"]),
                confidence=float(row["confidence"]),
                rationale=str(row["rationale"]))

    def _save(self) -> None:
        data = {k: {"direction": v.direction, "confidence": v.confidence,
                    "rationale": v.rationale}
                for k, v in self._cache.items()}
        self._path.write_text(json.dumps(data, indent=2, sort_keys=True))

    def classify(self, item: NewsItem) -> Classification:
        key = _content_hash(item)
        if key in self._cache:
            return self._cache[key]
        result = self._inner.classify(item)
        self._cache[key] = result
        self._save()
        return result


def _content_hash(item: NewsItem) -> str:
    text = f"{item.source}|{item.headline}|{item.body}".encode("utf-8")
    return hashlib.sha256(text).hexdigest()


class NewsSignal:
    """Scores symbols by the average direction of their recent news.

    A symbol with no news, or whose news the classifier abstains on, gets
    NO_OPINION — missing news is not a bearish view.
    """

    name = "news_llm"

    def __init__(self, classifier: Classifier,
                 max_age_days: int = MAX_NEWS_AGE_DAYS,
                 lookback: int = LOOKBACK_ITEMS) -> None:
        self.classifier = classifier
        self.max_age_days = max_age_days
        self.lookback = lookback

    def score(self, store: FeatureStore, as_of: dt.date,
              universe: Sequence[str]) -> dict[str, Score]:
        items = store.news_as_of(as_of, list(universe), lookback=self.lookback)
        out: dict[str, Score] = {}
        for symbol in universe:
            recent = [i for i in items.get(symbol, [])
                      if (as_of - i.knowable_at).days <= self.max_age_days]
            if not recent:
                out[symbol] = NO_OPINION
                continue

            total = 0.0
            weight = 0.0
            parts: list[str] = []
            for item in recent:
                try:
                    c = self.classifier.classify(item)
                except Exception:
                    continue  # classifier failure → abstain on this item
                if c.confidence <= 0.0:
                    continue  # abstention is not a view
                total += c.direction * c.confidence
                weight += c.confidence
                parts.append(f"{c.direction:+.1f}")

            if weight == 0.0:
                out[symbol] = NO_OPINION
                continue

            value = total / weight
            out[symbol] = Score(
                value=value,
                confidence=1.0,
                rationale=(f"news {value:+.2f} over {len(parts)} item(s) "
                           f"({', '.join(parts)})"),
            )
        return out