"""Live news ingestion and LLM classification.

The news signal cannot be honestly backtested: any modern LLM was trained on
data including what happened after a historical headline, so classifying old
news leaks the outcome. That lookahead sits in the model weights where the
point-in-time store cannot detect it. The only honest evaluation is forward —
live feed, live classifications, an out-of-sample record accumulated in real
time.
"""
import datetime as dt
import hashlib
import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

from .store.store import NewsItem
from .signals.news import Classification, Classifier


def parse_yahoo_news(payload: dict, symbol: str, max_age_hours: int = 36) -> list[NewsItem]:
    """Parse Yahoo Finance news payload into NewsItems.

    Pure function so it is testable without network. A week-old opinion column
    is not information about today, and stale items would dilute the average
    the signal computes.
    """
    items: list[NewsItem] = []
    entries = payload.get("news", [])
    if not isinstance(entries, list):
        return items

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=max_age_hours)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        title = entry.get("title")
        publish_time = entry.get("providerPublishTime")
        if not isinstance(title, str) or not isinstance(publish_time, int):
            continue  # feed changing shape must not take the cycle down
        published_at = dt.datetime.fromtimestamp(publish_time, tz=dt.timezone.utc)
        if published_at < cutoff:
            continue
        content_hash = hashlib.sha256(
            f"{symbol}|{title}".encode("utf-8")).hexdigest()
        items.append(NewsItem(
            symbol=symbol,
            published_at=published_at,
            source=entry.get("publisher", "yahoo"),
            headline=title,
            body="",
            content_hash=content_hash,
            knowable_at=published_at.date(),
        ))
    return items


class YahooNewsSource:
    """Live news source implementing the NewsSource protocol.

    A dead feed must degrade to "no news", which the signal already treats as
    abstention — never raise.
    """

    def __init__(self, pause_seconds: float = 0.3, max_age_hours: int = 36) -> None:
        self.pause_seconds = pause_seconds
        self.max_age_hours = max_age_hours

    def fetch(self, symbol: str) -> list[NewsItem]:
        """Fetch and parse news for a symbol, returning [] on any failure."""
        try:
            params = urllib.parse.urlencode({
                "q": symbol,
                "newsCount": 10,
                "quotesCount": 0,
            })
            url = f"https://query1.finance.yahoo.com/v1/finance/search?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            result = parse_yahoo_news(payload, symbol, self.max_age_hours)
            time.sleep(self.pause_seconds)
            return result
        except (urllib.error.URLError, json.JSONDecodeError, OSError, KeyError):
            return []


class DeepSeekClassifier:
    """LLM classifier implementing the Classifier protocol.

    Injection of `caller` lets tests run without network or cost. The cache
    keyed on content hash means a repeated hash never calls the caller again —
    every call is billed and the same headline reaches many symbols.
    """

    def __init__(self, caller: Optional[Callable[[str, str], str]] = None,
                 model: str = "deepseek-v4-flash",
                 key_path: str = "~/.config/deepseek/key") -> None:
        self._model = model
        self._key_path = pathlib.Path(key_path).expanduser()
        self._caller = caller if caller is not None else self._default_caller
        self._cache: dict[str, Classification] = {}

    def _default_caller(self, system: str, user: str) -> str:
        """POST to DeepSeek API and return the raw reply text."""
        key = self._key_path.read_text().strip()
        body = json.dumps({
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "thinking": {"type": "disabled"},
            "temperature": 0.0,
            "max_tokens": 200,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"},
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    def classify(self, item: NewsItem) -> Classification:
        """Classify a news item, caching by content hash.

        Any failure returns zero confidence — a failure must never become a
        directional view; the signal treats zero confidence as abstention.
        """
        if item.content_hash in self._cache:
            return self._cache[item.content_hash]

        system = (
            "You are a financial news classifier. Reply with ONLY a JSON object "
            '{"direction": <float -1..1>, "confidence": <float 0..1>, '
            '"rationale": "<short>"}, where direction is the likely effect on '
            "that company's share price and confidence is 0 when the item is "
            "not material to it."
        )
        user = f"Symbol: {item.symbol}\nHeadline: {item.headline}"

        try:
            reply = self._caller(system, user)
            result = self._parse_reply(reply)
        except Exception as exc:
            result = Classification(direction=0.0, confidence=0.0,
                                    rationale=f"failure: {type(exc).__name__}")

        self._cache[item.content_hash] = result
        return result

    @staticmethod
    def _parse_reply(reply: str) -> Classification:
        """Extract and validate the JSON object from the model's reply."""
        try:
            start = reply.index("{")
            end = reply.rindex("}") + 1
            data = json.loads(reply[start:end])
            direction = float(data["direction"])
            confidence = float(data["confidence"])
            rationale = str(data.get("rationale", ""))[:200]
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return Classification(direction=0.0, confidence=0.0,
                                  rationale="unparseable reply")

        direction = max(-1.0, min(1.0, direction))
        confidence = max(0.0, min(1.0, confidence))
        return Classification(direction=direction, confidence=confidence,
                              rationale=rationale)
