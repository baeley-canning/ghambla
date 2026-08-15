"""The in-memory bar cache must be indistinguishable from the SQL path.

A fast path that quietly disagrees with the audited one would corrupt every
number this project produces. These tests compare the two directly, on every
as-of date, rather than asserting the cache is "correct" in isolation.
"""
import datetime as dt

import pytest

from ghambla.store.store import Bar, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "cache.db")
    bars = []
    day = d("2026-01-01")
    for i in range(40):
        # AAA trades every day; BBB has gaps; CCC stops halfway (delisting)
        bars.append(Bar("AAA", day, 100 + i, 100 + i, 100 + i, 100 + i, 100 + i, 1000))
        if i % 3 != 0:
            bars.append(Bar("BBB", day, 50 + i, 50 + i, 50 + i, 50 + i, 50 + i, 1000))
        if i < 20:
            bars.append(Bar("CCC", day, 25 + i, 25 + i, 25 + i, 25 + i, 25 + i, 1000))
        day += dt.timedelta(days=1)
    s.upsert_bars(bars)
    yield s
    s.close()


ALL = ["AAA", "BBB", "CCC", "MISSING"]


def test_cache_agrees_with_sql_on_every_as_of_date(store):
    """The load-bearing test. Any divergence anywhere is a corrupted backtest."""
    uncached = {}
    for i in range(45):
        as_of = d("2026-01-01") + dt.timedelta(days=i)
        uncached[as_of] = store.latest_bars_as_of(as_of, ALL)

    store.preload(d("2026-01-01"), d("2026-02-20"))
    for as_of, expected in uncached.items():
        assert store.latest_bars_as_of(as_of, ALL) == expected, f"diverged at {as_of}"


def test_preload_reports_what_it_loaded(store):
    assert store.preload(d("2026-01-01"), d("2026-02-20")) > 0


def test_a_delisted_symbol_carries_forward_identically(store):
    """CCC stops on day 20; both paths must keep returning its last bar."""
    late = d("2026-02-10")
    before = store.latest_bars_as_of(late, ["CCC"])
    store.preload(d("2026-01-01"), d("2026-02-20"))
    assert store.latest_bars_as_of(late, ["CCC"]) == before
    assert before["CCC"].date == d("2026-01-20")


def test_a_gappy_symbol_carries_forward_identically(store):
    for i in range(40):
        as_of = d("2026-01-01") + dt.timedelta(days=i)
        expected = store.latest_bars_as_of(as_of, ["BBB"])
        store.preload(d("2026-01-01"), d("2026-02-20"))
        assert store.latest_bars_as_of(as_of, ["BBB"]) == expected
        store.clear_cache()


def test_a_date_before_the_cached_range_falls_back_to_sql(store):
    store.preload(d("2026-01-20"), d("2026-02-20"))
    got = store.latest_bars_as_of(d("2026-01-05"), ["AAA"])
    assert got["AAA"].date == d("2026-01-05")


def test_a_date_after_the_cached_range_falls_back_to_sql(store):
    store.preload(d("2026-01-01"), d("2026-01-10"))
    got = store.latest_bars_as_of(d("2026-02-05"), ["AAA"])
    assert got["AAA"].date == d("2026-02-05")


def test_the_cache_cannot_return_the_future(store):
    """The point-in-time guarantee is not suspended by the fast path."""
    store.preload(d("2026-01-01"), d("2026-02-20"))
    for i in range(40):
        as_of = d("2026-01-01") + dt.timedelta(days=i)
        for bar in store.latest_bars_as_of(as_of, ALL).values():
            assert bar.date <= as_of


def test_clearing_the_cache_restores_the_sql_path(store):
    store.preload(d("2026-01-01"), d("2026-02-20"))
    store.clear_cache()
    got = store.latest_bars_as_of(d("2026-01-15"), ["AAA"])
    assert got["AAA"].date == d("2026-01-15")


def test_preloading_twice_replaces_rather_than_appends(store):
    store.preload(d("2026-01-01"), d("2026-02-20"))
    store.preload(d("2026-01-01"), d("2026-01-10"))
    # outside the new range, so it must fall back and still be right
    assert store.latest_bars_as_of(d("2026-02-05"), ["AAA"])["AAA"].date == d("2026-02-05")


def test_symbol_restricted_preload_still_serves_others_correctly(store):
    store.preload(d("2026-01-01"), d("2026-02-20"), symbols=["AAA"])
    got = store.latest_bars_as_of(d("2026-01-15"), ["AAA", "BBB"])
    assert got["AAA"].date == d("2026-01-15")
    assert "BBB" in got, "a symbol outside the preload must not vanish"


def test_unknown_symbols_are_absent_in_both_paths(store):
    before = store.latest_bars_as_of(d("2026-01-15"), ["MISSING"])
    store.preload(d("2026-01-01"), d("2026-02-20"))
    assert store.latest_bars_as_of(d("2026-01-15"), ["MISSING"]) == before == {}


def test_empty_symbol_list(store):
    store.preload(d("2026-01-01"), d("2026-02-20"))
    assert store.latest_bars_as_of(d("2026-01-15"), []) == {}
