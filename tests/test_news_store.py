"""News store point-in-time tests."""
import datetime as dt

import pytest

from ghambla.store.store import FeatureStore, NewsItem


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def item(sym, day, headline, body="", source="test", hash_=None):
    return NewsItem(symbol=sym, published_at=dt.datetime.fromisoformat(f"{day}T10:00:00"),
                    source=source, headline=headline, body=body,
                    content_hash=hash_ or f"h-{sym}-{day}-{headline}",
                    knowable_at=d(day))


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "news.db")
    yield s
    s.close()


def test_upsert_then_read_back(store):
    store.upsert_news([item("AAA", "2026-01-05", "AAA beats")])
    got = store.news_as_of(d("2026-01-05"), ["AAA"])
    assert len(got["AAA"]) == 1
    assert got["AAA"][0].headline == "AAA beats"


def test_news_is_point_in_time(store):
    store.upsert_news([item("AAA", "2026-01-05", "old"),
                       item("AAA", "2026-02-01", "new")])
    got = store.news_as_of(d("2026-01-15"), ["AAA"])
    assert [i.headline for i in got["AAA"]] == ["old"]


def test_news_returns_newest_first(store):
    store.upsert_news([item("AAA", "2026-01-05", "old"),
                       item("AAA", "2026-01-06", "new")])
    got = store.news_as_of(d("2026-01-06"), ["AAA"])
    assert [i.headline for i in got["AAA"]] == ["new", "old"]


def test_upsert_is_idempotent_on_content_hash(store):
    store.upsert_news([item("AAA", "2026-01-05", "same", hash_="k")])
    store.upsert_news([item("AAA", "2026-01-05", "same", hash_="k")])
    got = store.news_as_of(d("2026-01-05"), ["AAA"])
    assert len(got["AAA"]) == 1


def test_missing_symbol_yields_empty_list(store):
    store.upsert_news([item("AAA", "2026-01-05", "x")])
    assert store.news_as_of(d("2026-01-05"), ["BBB"]) == {}