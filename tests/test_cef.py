"""Closed-end fund discount signal.

The trap this file exists to catch: NAV is not distribution-adjusted while
adj_close is, and CEFs pay 8-12% a year. Using adj_close would show the
discount widening annually from dividends alone — an artefact that looks
exactly like a strengthening signal.
"""
import datetime as dt

import pytest

from ghambla.cef import all_symbols, is_nav_symbol, nav_symbol
from ghambla.signals.cef import CEFDiscountSignal
from ghambla.store.store import Bar, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "cef.db")
    yield s
    s.close()


def seed(store, sym, series, start="2024-01-01", adj_factor=1.0):
    """`series` is a list of raw closes. adj_factor skews adj_close away from
    close, standing in for accumulated distributions."""
    day = d(start)
    rows = []
    for px in series:
        rows.append(Bar(sym, day, px, px, px, px, px * adj_factor, 1000))
        day += dt.timedelta(days=1)
    store.upsert_bars(rows)
    return day - dt.timedelta(days=1)


# --- universe hygiene -----------------------------------------------------

def test_nav_symbol_convention():
    assert nav_symbol("gab") == "XGABX"
    assert is_nav_symbol("XGABX") is True
    assert is_nav_symbol("GAB") is False


def test_every_fund_has_a_nav_symbol_in_all_symbols():
    syms = set(all_symbols())
    assert nav_symbol("GAB") in syms and "GAB" in syms


def test_a_nav_ticker_is_never_scored(store):
    """Buying a NAV series is meaningless; it must not be selectable."""
    seed(store, "XGABX", [10.0] * 300)
    scores = CEFDiscountSignal().score(store, d("2024-10-01"), ["XGABX"])
    assert scores["XGABX"].confidence == 0.0


# --- the distribution trap ------------------------------------------------

def test_discount_uses_raw_close_not_adjusted_close(store):
    """Price and NAV both flat, but adj_close drifts 30% from distributions.
    A signal reading adj_close would report a large fake discount."""
    last = seed(store, "AAA", [9.0] * 300, adj_factor=1.30)
    seed(store, "XAAAX", [10.0] * 300)
    scores = CEFDiscountSignal().score(store, last, ["AAA"])
    # constant discount -> zero stdev -> abstain, NOT a huge z from adj_close
    assert scores["AAA"].confidence == 0.0


def test_a_widening_discount_scores_positive(store):
    nav = [10.0] * 300
    price = [9.5] * 260 + [8.5] * 40          # discount widens late
    last = seed(store, "WIDE", price, adj_factor=1.25)
    seed(store, "XWIDEX", nav)
    got = CEFDiscountSignal().score(store, last, ["WIDE"])["WIDE"]
    assert got.confidence == 1.0
    assert got.value > 0


def test_a_narrowing_discount_scores_negative(store):
    nav = [10.0] * 300
    price = [8.5] * 260 + [9.8] * 40          # discount narrows late
    last = seed(store, "TIGHT", price)
    seed(store, "XTIGHTX", nav)
    got = CEFDiscountSignal().score(store, last, ["TIGHT"])["TIGHT"]
    assert got.value < 0


def test_a_fund_at_a_permanent_premium_is_not_penalised_for_it(store):
    """GUT trades at +100% for years. Ranking on the raw level would sort funds
    by permanent character; the z-score asks 'unusual for itself'."""
    seed(store, "PREM", [20.0] * 260 + [22.0] * 40)   # premium widens further
    seed(store, "XPREMX", [10.0] * 300)
    last = d("2024-10-25")
    got = CEFDiscountSignal().score(store, last, ["PREM"])["PREM"]
    # premium got richer, so it is unusually EXPENSIVE -> negative score
    assert got.value < 0


# --- abstention -----------------------------------------------------------

def test_missing_nav_abstains(store):
    last = seed(store, "NONAV", [9.0] * 300)
    assert CEFDiscountSignal().score(store, last, ["NONAV"])["NONAV"].confidence == 0.0


def test_short_history_abstains(store):
    last = seed(store, "SHORT", [9.0] * 50)
    seed(store, "XSHORTX", [10.0] * 50)
    assert CEFDiscountSignal().score(store, last, ["SHORT"])["SHORT"].confidence == 0.0


def test_constant_discount_abstains_rather_than_dividing_by_noise(store):
    last = seed(store, "FLAT", [9.0] * 300)
    seed(store, "XFLATX", [10.0] * 300)
    assert CEFDiscountSignal().score(store, last, ["FLAT"])["FLAT"].confidence == 0.0


def test_non_positive_nav_abstains(store):
    last = seed(store, "BAD", [9.0] * 300)
    seed(store, "XBADX", [0.0] * 300)
    assert CEFDiscountSignal().score(store, last, ["BAD"])["BAD"].confidence == 0.0


def test_rejects_a_tiny_lookback():
    with pytest.raises(ValueError):
        CEFDiscountSignal(lookback_days=10)


def test_reads_only_point_in_time_data(store):
    seed(store, "AAA", [9.5] * 260 + [8.5] * 40)
    seed(store, "XAAAX", [10.0] * 300)
    early = CEFDiscountSignal().score(store, d("2024-02-01"), ["AAA"])
    assert early["AAA"].confidence == 0.0
