"""Real news source and real LLM classifier.

These are the two seams the news signal was built around. Both are tested
against fakes here — the live versions hit the network and cost money, so they
are exercised by an opt-in integration test, not by the suite.

The signal cannot be honestly backtested: any modern LLM was trained on data
that includes what happened after a historical headline, so classifying old
news leaks the outcome. That lookahead lives in the model weights where the
point-in-time store cannot see it. The only honest evaluation is forward — real
feed, live classifications, an out-of-sample record accumulated in real time.
"""
import datetime as dt
import json

import pytest

from ghambla.news_live import DeepSeekClassifier, YahooNewsSource, parse_yahoo_news
from ghambla.store.store import NewsItem


def _payload(items):
    return {"news": [{"title": t, "publisher": p, "providerPublishTime": ts,
                      "link": f"https://example.test/{i}"}
                     for i, (t, p, ts) in enumerate(items)]}


def test_parses_headlines_into_news_items():
    now = int(dt.datetime.now(dt.UTC).timestamp())
    items = parse_yahoo_news(_payload([("NVDA beats on revenue", "Reuters", now)]), "NVDA")
    assert len(items) == 1
    assert items[0].symbol == "NVDA"
    assert items[0].headline == "NVDA beats on revenue"
    assert items[0].source == "Reuters"


def test_stale_items_are_dropped_at_the_source():
    """A week-old opinion piece is not information about today."""
    now = dt.datetime.now(dt.UTC)
    old = int((now - dt.timedelta(hours=200)).timestamp())
    fresh = int((now - dt.timedelta(hours=2)).timestamp())
    items = parse_yahoo_news(_payload([("stale", "X", old), ("fresh", "Y", fresh)]),
                             "NVDA", max_age_hours=36)
    assert [i.headline for i in items] == ["fresh"]


def test_content_hash_is_stable_and_distinct():
    """The cache keys on it, so identical text must hash identically."""
    now = int(dt.datetime.now(dt.UTC).timestamp())
    a = parse_yahoo_news(_payload([("same text", "X", now)]), "NVDA")[0]
    b = parse_yahoo_news(_payload([("same text", "X", now)]), "NVDA")[0]
    c = parse_yahoo_news(_payload([("other text", "X", now)]), "NVDA")[0]
    assert a.content_hash == b.content_hash
    assert a.content_hash != c.content_hash


def test_malformed_entries_are_skipped_not_fatal():
    payload = {"news": [{"title": "ok", "providerPublishTime": int(dt.datetime.now(dt.UTC).timestamp())},
                        {"no_title": True}, {"title": "missing time"}]}
    assert [i.headline for i in parse_yahoo_news(payload, "NVDA")] == ["ok"]


def test_empty_payload_is_empty_list():
    assert parse_yahoo_news({}, "NVDA") == []


# --- classifier ---------------------------------------------------------


def _item(headline="NVDA beats on revenue"):
    return NewsItem(symbol="NVDA", published_at=dt.datetime.now(dt.UTC), source="Reuters",
                    headline=headline, body="", content_hash="h1",
                    knowable_at=dt.date.today())


class FakeCaller:
    def __init__(self, reply): self.reply = reply; self.calls = 0
    def __call__(self, system, user):
        self.calls += 1
        return self.reply


def test_classifier_parses_a_well_formed_verdict():
    c = DeepSeekClassifier(caller=FakeCaller(json.dumps(
        {"direction": 0.8, "confidence": 0.6, "rationale": "revenue beat"})))
    got = c.classify(_item())
    assert got.direction == pytest.approx(0.8)
    assert got.confidence == pytest.approx(0.6)


def test_unparseable_reply_abstains_rather_than_guessing():
    """A failure must never become a directional view."""
    got = DeepSeekClassifier(caller=FakeCaller("I think it's probably good?")).classify(_item())
    assert got.confidence == 0.0


def test_caller_exception_abstains():
    def boom(system, user): raise RuntimeError("api down")
    assert DeepSeekClassifier(caller=boom).classify(_item()).confidence == 0.0


def test_out_of_range_values_are_clamped_not_trusted():
    c = DeepSeekClassifier(caller=FakeCaller(json.dumps(
        {"direction": 9.0, "confidence": 5.0, "rationale": "x"})))
    got = c.classify(_item())
    assert -1.0 <= got.direction <= 1.0
    assert 0.0 <= got.confidence <= 1.0


def test_identical_text_is_only_classified_once():
    """Every call is billed; the same headline must not be re-sent."""
    caller = FakeCaller(json.dumps({"direction": 0.5, "confidence": 0.5, "rationale": "x"}))
    c = DeepSeekClassifier(caller=caller)
    c.classify(_item()); c.classify(_item())
    assert caller.calls == 1
