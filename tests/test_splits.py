import datetime as dt

import pytest

from ghambla.store.ingest import parse_yahoo_splits
from ghambla.store.store import FeatureStore, Split, split_factor_after


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


PAYLOAD = {
    "chart": {"result": [{
        "events": {"splits": {
            "1625097600": {"date": 1625097600, "numerator": 4.0, "denominator": 1.0,
                            "splitRatio": "4:1"},
            "1717200000": {"date": 1717200000, "numerator": 10.0, "denominator": 1.0,
                            "splitRatio": "10:1"},
        }}
    }]}
}


def test_parses_splits_in_date_order():
    got = parse_yahoo_splits(PAYLOAD, "NVDA")
    assert [s.ratio for s in got] == [4.0, 10.0]
    assert got[0].date < got[1].date


def test_no_events_yields_nothing():
    assert parse_yahoo_splits({"chart": {"result": [{}]}}, "EMR") == []


def test_factor_is_one_when_nothing_happened_after():
    splits = [(d("2021-07-01"), 4.0)]
    assert split_factor_after(splits, d("2024-01-01")) == 1.0


def test_factor_compounds_later_splits():
    splits = [(d("2021-07-01"), 4.0), (d("2024-06-10"), 10.0)]
    assert split_factor_after(splits, d("2020-01-01")) == pytest.approx(40.0)


def test_factor_excludes_splits_on_or_before_the_date():
    splits = [(d("2024-06-10"), 10.0)]
    assert split_factor_after(splits, d("2024-06-10")) == 1.0


def test_nvidia_market_cap_is_restored_to_reality():
    """The concrete bug. NVDA filed 2.494bn shares in Feb 2024; the stored
    price for 3 June 2024 is already divided by the 10-for-1 split that
    followed on 10 June. Multiplying the two naively gives $287bn against a
    real market cap near $2.9tn, making the most expensive stock in the index
    look like a bargain."""
    splits = [(d("2021-07-01"), 4.0), (d("2024-06-10"), 10.0)]
    shares_filed, filed_on, adjusted_price = 2.494e9, d("2024-02-21"), 115.0

    naive = shares_filed * adjusted_price
    corrected = shares_filed * adjusted_price * split_factor_after(splits, filed_on)

    assert naive == pytest.approx(2.87e11, rel=0.02)
    assert corrected == pytest.approx(2.87e12, rel=0.02)


def test_store_round_trip(tmp_path):
    s = FeatureStore(tmp_path / "sp.db")
    try:
        s.upsert_splits([Split("NVDA", d("2024-06-10"), 10.0),
                         Split("NVDA", d("2021-07-01"), 4.0)])
        got = s.splits_for(["NVDA", "EMR"])
        assert [r[1] for r in got["NVDA"]] == [4.0, 10.0]
        assert "EMR" not in got
    finally:
        s.close()


def test_store_upsert_is_idempotent(tmp_path):
    s = FeatureStore(tmp_path / "sp.db")
    try:
        s.upsert_splits([Split("NVDA", d("2024-06-10"), 10.0)])
        s.upsert_splits([Split("NVDA", d("2024-06-10"), 10.0)])
        assert len(s.splits_for(["NVDA"])["NVDA"]) == 1
    finally:
        s.close()


def test_empty_symbol_list(tmp_path):
    s = FeatureStore(tmp_path / "sp.db")
    try:
        assert s.splits_for([]) == {}
    finally:
        s.close()
