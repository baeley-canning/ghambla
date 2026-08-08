"""News signal tests: caching, abstention, and scoring."""
import datetime as dt

import pytest

from ghambla.signals.news import (
    CachedClassifier,
    Classification,
    NewsSignal,
    StubClassifier,
)
from ghambla.store.store import FeatureStore, NewsItem


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def item(sym, day, headline, body="", source="test"):
    return NewsItem(symbol=sym, published_at=dt.datetime.fromisoformat(f"{day}T10:00:00"),
                    source=source, headline=headline, body=body,
                    content_hash=f"h-{sym}-{day}-{headline}",
                    knowable_at=d(day))


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "news.db")
    yield s
    s.close()


class FixedClassifier:
    """Returns a canned classification, counting calls."""

    def __init__(self, direction=1.0, confidence=1.0):
        self.direction = direction
        self.confidence = confidence
        self.calls = 0

    def classify(self, item):
        self.calls += 1
        return Classification(self.direction, self.confidence, "stub")


class FailingClassifier:
    def classify(self, item):
        raise RuntimeError("LLM API down")


def test_positive_news_scores_positive(store):
    store.upsert_news([item("AAA", "2026-01-05", "AAA beats expectations")])
    scores = NewsSignal(StubClassifier()).score(store, d("2026-01-06"), ["AAA"])
    assert scores["AAA"].value > 0
    assert scores["AAA"].confidence == 1.0


def test_negative_news_scores_negative(store):
    store.upsert_news([item("AAA", "2026-01-05", "AAA misses and plunges")])
    scores = NewsSignal(StubClassifier()).score(store, d("2026-01-06"), ["AAA"])
    assert scores["AAA"].value < 0


def test_no_news_is_abstention_not_bearish(store):
    scores = NewsSignal(StubClassifier()).score(store, d("2026-01-06"), ["AAA"])
    assert scores["AAA"].confidence == 0.0
    assert scores["AAA"].value == 0.0


def test_stale_news_is_ignored(store):
    store.upsert_news([item("AAA", "2026-01-01", "AAA beats")])
    scores = NewsSignal(StubClassifier(), max_age_days=7).score(store, d("2026-01-20"), ["AAA"])
    assert scores["AAA"].confidence == 0.0


def test_classifier_failure_is_abstention(store):
    store.upsert_news([item("AAA", "2026-01-05", "AAA beats")])
    scores = NewsSignal(FailingClassifier()).score(store, d("2026-01-06"), ["AAA"])
    assert scores["AAA"].confidence == 0.0


def test_cached_classifier_does_not_reclassify_same_item(tmp_path):
    inner = FixedClassifier()
    cached = CachedClassifier(inner, tmp_path / "cache.json")
    item1 = item("AAA", "2026-01-05", "AAA beats")
    cached.classify(item1)
    cached.classify(item1)
    assert inner.calls == 1


def test_cached_classifier_persists_across_instances(tmp_path):
    inner = FixedClassifier()
    path = tmp_path / "cache.json"
    CachedClassifier(inner, path).classify(item("AAA", "2026-01-05", "AAA beats"))
    inner2 = FixedClassifier()
    cached2 = CachedClassifier(inner2, path)
    cached2.classify(item("AAA", "2026-01-05", "AAA beats"))
    assert inner2.calls == 0  # served from disk cache


def test_averaging_over_multiple_items(store):
    store.upsert_news([item("AAA", "2026-01-05", "AAA beats"),
                       item("AAA", "2026-01-06", "AAA misses")])
    scores = NewsSignal(StubClassifier()).score(store, d("2026-01-07"), ["AAA"])
    # +1 and -1 average to ~0, but confidence is still 1.0 (it had an opinion)
    assert scores["AAA"].confidence == 1.0