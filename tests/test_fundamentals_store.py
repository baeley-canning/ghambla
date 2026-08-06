import datetime as dt

import pytest

from ghambla.store.store import Fact, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def fact(sym, concept, period_end, value, filed, accn="a1"):
    return Fact(symbol=sym, concept=concept, period_end=d(period_end), value=value,
                knowable_at=d(filed), accn=accn)


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "f.db")
    yield s
    s.close()


def test_round_trip(store):
    store.upsert_fundamentals([fact("AAPL", "NetIncomeLoss", "2025-09-30", 1e9, "2025-11-01")])
    got = store.latest_fundamentals_as_of(d("2025-12-01"), "NetIncomeLoss", ["AAPL"])
    assert got["AAPL"].value == 1e9


def test_a_figure_is_invisible_before_it_is_filed(store):
    """The period ended in September but nobody knew the number until November."""
    store.upsert_fundamentals([fact("AAPL", "NetIncomeLoss", "2025-09-30", 1e9, "2025-11-01")])
    assert store.latest_fundamentals_as_of(d("2025-10-15"), "NetIncomeLoss", ["AAPL"]) == {}


def test_latest_filing_wins(store):
    store.upsert_fundamentals([
        fact("AAPL", "NetIncomeLoss", "2024-09-30", 1e9, "2024-11-01", accn="a1"),
        fact("AAPL", "NetIncomeLoss", "2025-09-30", 2e9, "2025-11-01", accn="a2"),
    ])
    got = store.latest_fundamentals_as_of(d("2026-01-01"), "NetIncomeLoss", ["AAPL"])
    assert got["AAPL"].value == 2e9


def test_only_the_filing_available_at_the_time_is_used(store):
    store.upsert_fundamentals([
        fact("AAPL", "NetIncomeLoss", "2024-09-30", 1e9, "2024-11-01", accn="a1"),
        fact("AAPL", "NetIncomeLoss", "2025-09-30", 2e9, "2025-11-01", accn="a2"),
    ])
    got = store.latest_fundamentals_as_of(d("2025-06-01"), "NetIncomeLoss", ["AAPL"])
    assert got["AAPL"].value == 1e9


def test_concepts_do_not_bleed_into_each_other(store):
    store.upsert_fundamentals([
        fact("AAPL", "NetIncomeLoss", "2025-09-30", 1e9, "2025-11-01", accn="a1"),
        fact("AAPL", "StockholdersEquity", "2025-09-30", 5e10, "2025-11-01", accn="a1"),
    ])
    got = store.latest_fundamentals_as_of(d("2026-01-01"), "StockholdersEquity", ["AAPL"])
    assert got["AAPL"].value == 5e10


def test_unknown_symbol_is_absent(store):
    store.upsert_fundamentals([fact("AAPL", "NetIncomeLoss", "2025-09-30", 1e9, "2025-11-01")])
    got = store.latest_fundamentals_as_of(d("2026-01-01"), "NetIncomeLoss", ["AAPL", "MSFT"])
    assert "MSFT" not in got


def test_upsert_is_idempotent(store):
    f = fact("AAPL", "NetIncomeLoss", "2025-09-30", 1e9, "2025-11-01")
    store.upsert_fundamentals([f])
    store.upsert_fundamentals([f])
    got = store.latest_fundamentals_as_of(d("2026-01-01"), "NetIncomeLoss", ["AAPL"])
    assert got["AAPL"].value == 1e9


def test_empty_symbol_list_is_empty(store):
    assert store.latest_fundamentals_as_of(d("2026-01-01"), "NetIncomeLoss", []) == {}
