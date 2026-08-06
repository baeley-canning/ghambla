import datetime as dt

import pytest

from ghambla.edgar import EQUITY, NET_INCOME, SHARES
from ghambla.signals.fundamental import FundamentalSignal
from ghambla.store.store import Bar, Fact, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "fs.db")
    yield s
    s.close()


def seed(store, sym, price, net_income, equity, shares,
         filed="2025-11-01", period_end="2025-09-30", bar_date="2026-01-05"):
    store.upsert_bars([Bar(sym, d(bar_date), price, price, price, price, price, 1000)])
    store.upsert_fundamentals([
        Fact(sym, NET_INCOME, d(period_end), net_income, d(filed), f"{sym}-a"),
        Fact(sym, EQUITY, d(period_end), equity, d(filed), f"{sym}-a"),
        Fact(sym, SHARES, d(period_end), shares, d(filed), f"{sym}-a"),
    ])


def test_cheap_profitable_company_outranks_expensive_unprofitable_one(store):
    # CHEAP: mcap 100 * 1000 = 100k, NI 20k -> 20% yield, ROE 20%
    seed(store, "CHEAP", price=100.0, net_income=20_000, equity=100_000, shares=1000)
    # RICH: mcap 1000 * 1000 = 1m, NI 5k -> 0.5% yield, ROE 5%
    seed(store, "RICH", price=1000.0, net_income=5_000, equity=100_000, shares=1000)
    scores = FundamentalSignal().score(store, d("2026-02-01"), ["CHEAP", "RICH"])
    assert scores["CHEAP"].value > scores["RICH"].value


def test_figures_are_invisible_before_they_are_filed(store):
    seed(store, "AAA", 100.0, 20_000, 100_000, 1000, filed="2025-11-01")
    seed(store, "BBB", 100.0, 10_000, 100_000, 1000, filed="2025-11-01")
    # as-of precedes the filing date, so nothing is knowable yet
    scores = FundamentalSignal().score(store, d("2025-10-01"), ["AAA", "BBB"])
    assert scores["AAA"].confidence == 0.0
    assert scores["BBB"].confidence == 0.0


def test_negative_book_value_yields_no_opinion(store):
    seed(store, "NEG", 100.0, 20_000, -50_000, 1000)
    seed(store, "OK", 100.0, 20_000, 100_000, 1000)
    scores = FundamentalSignal().score(store, d("2026-02-01"), ["NEG", "OK"])
    assert scores["NEG"].confidence == 0.0


def test_missing_fundamentals_yield_no_opinion(store):
    store.upsert_bars([Bar("BARE", d("2026-01-05"), 10.0, 10.0, 10.0, 10.0, 10.0, 1000)])
    scores = FundamentalSignal().score(store, d("2026-02-01"), ["BARE"])
    assert scores["BARE"].confidence == 0.0


def test_missing_price_yields_no_opinion(store):
    store.upsert_fundamentals([
        Fact("NOPX", NET_INCOME, d("2025-09-30"), 1e6, d("2025-11-01"), "x"),
        Fact("NOPX", EQUITY, d("2025-09-30"), 1e7, d("2025-11-01"), "x"),
        Fact("NOPX", SHARES, d("2025-09-30"), 1e5, d("2025-11-01"), "x"),
    ])
    scores = FundamentalSignal().score(store, d("2026-02-01"), ["NOPX"])
    assert scores["NOPX"].confidence == 0.0


def test_a_company_that_stopped_reporting_goes_stale(store):
    seed(store, "STALE", 100.0, 20_000, 100_000, 1000, filed="2020-01-01",
         period_end="2019-09-30")
    scores = FundamentalSignal().score(store, d("2026-02-01"), ["STALE"])
    assert scores["STALE"].confidence == 0.0


def test_scores_are_cross_sectional_so_the_average_name_sits_near_zero(store):
    for i, sym in enumerate(["A", "B", "C", "D", "E"]):
        seed(store, sym, price=100.0, net_income=10_000 * (i + 1),
             equity=100_000, shares=1000)
    scores = FundamentalSignal().score(store, d("2026-02-01"), ["A", "B", "C", "D", "E"])
    values = [s.value for s in scores.values()]
    assert sum(values) == pytest.approx(0.0, abs=1e-9)


def test_identical_companies_all_score_zero(store):
    for sym in ["A", "B", "C"]:
        seed(store, sym, 100.0, 10_000, 100_000, 1000)
    scores = FundamentalSignal().score(store, d("2026-02-01"), ["A", "B", "C"])
    assert all(s.value == pytest.approx(0.0) for s in scores.values())


def test_misfiled_share_count_is_rejected_not_ranked_top(store):
    """WRB filed its share count in thousands, implying a 9,468% earnings
    yield. Unfiltered, that ranks as the most attractive stock in the index."""
    # 273,298 shares at $50 implies a $13.7m market cap against $1.38bn income.
    seed(store, "BROKEN", price=50.0, net_income=1_381_359_000,
         equity=7_784_832_000, shares=273_298)
    seed(store, "FINE", price=50.0, net_income=1_000_000, equity=10_000_000, shares=1_000_000)
    scores = FundamentalSignal().score(store, d("2026-02-01"), ["BROKEN", "FINE"])
    assert scores["BROKEN"].confidence == 0.0


def test_near_zero_book_equity_is_rejected(store):
    """Colgate: 2.3bn income on 230m equity is a 1000% ROE — arithmetically
    right, financially meaningless, and it would swamp every z-score."""
    seed(store, "NOBOOK", price=80.0, net_income=2_300_000_000,
         equity=230_000_000, shares=829_200_000)
    scores = FundamentalSignal().score(store, d("2026-02-01"), ["NOBOOK"])
    assert scores["NOBOOK"].confidence == 0.0


def test_a_single_outlier_cannot_dominate_the_ranking(store):
    """Winsorising keeps one extreme name from compressing everyone else."""
    for i, sym in enumerate(["A", "B", "C", "D", "E", "F", "G"]):
        seed(store, sym, price=100.0, net_income=1_000_000 + i * 10_000,
             equity=50_000_000, shares=1_000_000)
    # H is a legitimate but extreme value, well inside the plausibility bounds
    seed(store, "H", price=100.0, net_income=90_000_000, equity=100_000_000,
         shares=1_000_000)
    syms = ["A", "B", "C", "D", "E", "F", "G", "H"]
    scores = FundamentalSignal().score(store, d("2026-02-01"), syms)
    spread = max(s.value for s in scores.values()) - min(s.value for s in scores.values())
    assert spread < 6.0, "one name is still swamping the distribution"


def test_rationale_reports_both_components(store):
    seed(store, "AAA", 100.0, 20_000, 100_000, 1000)
    seed(store, "BBB", 100.0, 10_000, 100_000, 1000)
    r = FundamentalSignal().score(store, d("2026-02-01"), ["AAA", "BBB"])["AAA"].rationale
    assert "earnings yield" in r
    assert "ROE" in r
