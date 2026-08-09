import datetime as dt

import pytest

from ghambla.backtest import run_backtest
from ghambla.signals.base import Score
from ghambla.store.store import Bar, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


class AlwaysBuy:
    """Signal stub that always favours one symbol."""
    name = "always_buy"

    def __init__(self, symbol="AAA"):
        self.symbol = symbol

    def score(self, store, as_of, universe):
        return {s: Score(value=1.0 if s == self.symbol else -1.0,
                         confidence=1.0, rationale="stub") for s in universe}


class NeverBuy:
    name = "never_buy"

    def score(self, store, as_of, universe):
        return {s: Score(value=-1.0, confidence=1.0, rationale="stub") for s in universe}


@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "bt.db")
    day = d("2026-01-01")
    bars = []
    for i in range(60):
        # open deliberately differs from close so a close-filling bug is visible
        bars.append(Bar(symbol="AAA", date=day, open=100.0 + i, high=110.0 + i,
                        low=90.0 + i, close=105.0 + i, adj_close=105.0 + i, volume=10_000))
        day += dt.timedelta(days=1)
    s.upsert_bars(bars)
    s.set_universe(d("2025-12-01"), ["AAA"])
    yield s
    s.close()


def test_no_trades_when_signal_never_buys(store):
    r = run_backtest(store, NeverBuy(), d("2026-01-01"), d("2026-02-28"), initial_cash=10_000.0)
    assert r.trades == []
    assert r.equity[-1] == pytest.approx(10_000.0)


def test_fills_at_next_bar_open_not_signal_bar_close(store):
    """The rule the whole engine exists to enforce."""
    dates = store.trading_dates(d("2026-01-01"), d("2026-02-28"))
    r = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0, rebalance_every=1000, spread_bps=0.0)
    assert r.trades, "expected at least one trade"
    first = r.trades[0]

    # Decision is taken on dates[0]'s close, so the fill must land on dates[1].
    assert first.date == dates[1]

    decision_bar = store.bars_as_of(dates[0], ["AAA"], lookback=1)["AAA"][-1]
    fill_bar = store.bars_as_of(dates[1], ["AAA"], lookback=1)["AAA"][-1]

    assert first.price == pytest.approx(fill_bar.open)
    assert first.price != pytest.approx(decision_bar.close)


def test_commission_is_charged_on_every_trade(store):
    r = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"), initial_cash=10_000.0)
    assert r.trades
    assert all(t.commission > 0 for t in r.trades)


def test_equity_curve_has_one_point_per_trading_day(store):
    r = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"), initial_cash=10_000.0)
    expected = store.trading_dates(d("2026-01-01"), d("2026-02-28"))
    assert r.dates == expected
    assert len(r.equity) == len(expected)


def test_equity_never_goes_negative(store):
    r = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0, rebalance_every=1)
    assert all(e >= 0 for e in r.equity)


def test_spread_makes_buys_more_expensive_than_the_open(store):
    r = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0, rebalance_every=1000, spread_bps=100.0)
    first = r.trades[0]
    fill_bar = store.bars_as_of(first.date, ["AAA"], lookback=1)["AAA"][-1]
    assert first.price > fill_bar.open


def test_empty_date_range_yields_empty_result(store):
    r = run_backtest(store, AlwaysBuy(), d("2020-01-01"), d("2020-12-31"))
    assert r.dates == []
    assert r.equity == []
    assert r.trades == []


def _delisting_store(tmp_path, dead_days=20, total_days=45):
    """AAA trades throughout; DEAD stops trading partway, as if acquired."""
    s = FeatureStore(tmp_path / "delist.db")
    day = d("2026-01-01")
    bars = []
    for i in range(total_days):
        bars.append(Bar("AAA", day, 100.0, 100.0, 100.0, 100.0, 100.0, 1000))
        if i < dead_days:
            bars.append(Bar("DEAD", day, 50.0, 50.0, 50.0, 50.0, 50.0, 1000))
        day += dt.timedelta(days=1)
    s.upsert_bars(bars)
    s.set_universe(d("2025-12-01"), ["AAA", "DEAD"])
    return s


class LikesDead:
    name = "likes_dead"

    def score(self, store, as_of, universe):
        return {sym: Score(value=1.0 if sym == "DEAD" else 0.5,
                           confidence=1.0, rationale="stub") for sym in universe}


def test_delisted_position_is_liquidated_at_last_known_close(tmp_path):
    """A holding whose security stops trading must be cashed out, not frozen.

    Carrying it at its last close forever would let a bankrupt company sit in
    the equity curve at full value.
    """
    s = _delisting_store(tmp_path)
    try:
        r = run_backtest(s, LikesDead(), d("2026-01-01"), d("2026-02-14"),
                         initial_cash=10_000.0, top_n=1, rebalance_every=1, spread_bps=0.0)
        sells = [t for t in r.trades if t.symbol == "DEAD" and t.side == "SELL"]
        assert sells, "delisted position was never liquidated"
        assert sells[-1].price == pytest.approx(50.0)
    finally:
        s.close()


def test_liquidation_converts_the_position_to_cash(tmp_path):
    s = _delisting_store(tmp_path)
    try:
        r = run_backtest(s, LikesDead(), d("2026-01-01"), d("2026-02-14"),
                         initial_cash=10_000.0, top_n=1, rebalance_every=1, spread_bps=0.0)
        # Once DEAD is gone the curve must stop moving with it; AAA is flat at
        # 100 and DEAD was flat at 50, so equity should settle and stay put.
        assert r.equity[-1] == pytest.approx(r.equity[-2], rel=1e-6)
    finally:
        s.close()


def test_a_one_day_data_gap_does_not_trigger_liquidation(tmp_path):
    """Holidays and single missing bars are not delistings."""
    s = FeatureStore(tmp_path / "gap.db")
    try:
        day = d("2026-01-01")
        bars = []
        for i in range(40):
            bars.append(Bar("AAA", day, 100.0, 100.0, 100.0, 100.0, 100.0, 1000))
            if i != 25:  # single missing bar
                bars.append(Bar("GAPPY", day, 50.0, 50.0, 50.0, 50.0, 50.0, 1000))
            day += dt.timedelta(days=1)
        s.upsert_bars(bars)
        s.set_universe(d("2025-12-01"), ["AAA", "GAPPY"])

        class LikesGappy:
            name = "likes_gappy"

            def score(self, store, as_of, universe):
                return {sym: Score(value=1.0 if sym == "GAPPY" else 0.5,
                                   confidence=1.0, rationale="stub") for sym in universe}

        r = run_backtest(s, LikesGappy(), d("2026-01-01"), d("2026-02-09"),
                         initial_cash=10_000.0, top_n=1, rebalance_every=1, spread_bps=0.0)
        forced = [t for t in r.trades if t.symbol == "GAPPY" and t.side == "SELL"
                  and t.shares > 0 and t.price == pytest.approx(50.0)]
        # A rebalance sell is fine; a full liquidation of the whole position is not.
        assert not any(t.shares > 100 for t in forced)
    finally:
        s.close()


def test_position_is_sold_when_signal_stops_liking_it(store):
    """Buy on the first decision, then flip the signal and confirm it exits."""
    dates = store.trading_dates(d("2026-01-01"), d("2026-02-28"))

    class FlipFlop:
        name = "flipflop"

        def score(self, store, as_of, universe):
            liked = as_of < dates[10]
            return {s: Score(value=1.0 if liked else -1.0, confidence=1.0,
                             rationale="stub") for s in universe}

    r = run_backtest(store, FlipFlop(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0, rebalance_every=5)
    sides = [t.side for t in r.trades]
    assert "BUY" in sides
    assert "SELL" in sides


# --- one signal, or several combined ------------------------------------


class RanksBackwards:
    """Prefers whatever AlwaysBuy dislikes, on a wildly different numeric scale."""
    name = "ranks_backwards"

    def __init__(self, symbol="AAA"):
        self.symbol = symbol

    def score(self, store, as_of, universe):
        return {s: Score(value=-500.0 if s == self.symbol else 500.0,
                         confidence=1.0, rationale="stub") for s in universe}


def test_signals_name_joins_sub_signal_names():
    from ghambla.backtest import signals_name
    assert signals_name(AlwaysBuy()) == "always_buy"
    assert signals_name({"a": AlwaysBuy(), "b": NeverBuy()}) == "always_buy+never_buy"


def test_a_single_signal_keeps_its_raw_scores(store):
    """Regression guard on the whole recorded result set.

    A lone signal must NOT be routed through the rank allocator. Rank-centring
    makes half the universe positive by construction, so an all-negative signal
    would start buying and every Gate 0 number on record would shift.
    """
    raw = run_backtest(store, NeverBuy(), d("2026-01-01"), d("2026-02-28"),
                       initial_cash=10_000.0)
    wrapped = run_backtest(store, {"never": NeverBuy()}, d("2026-01-01"),
                           d("2026-02-28"), initial_cash=10_000.0)
    assert raw.trades == [] and wrapped.trades == []
    assert raw.equity == wrapped.equity


def test_several_signals_are_combined_by_rank_not_by_raw_magnitude(store):
    """The allocator must rank within each signal before averaging.

    `RanksBackwards` emits values 500x larger than `AlwaysBuy`. If magnitudes
    were averaged directly it would dominate outright; under rank averaging the
    two cancel, which is the entire point of ranking.
    """
    from ghambla.allocator import RankAllocator
    from ghambla.backtest import score_universe

    signal_map = {"buy": AlwaysBuy(), "back": RanksBackwards()}
    scores = score_universe(store, d("2026-01-15"), ["AAA"], signal_map, RankAllocator())
    # Single-name universe: each signal ranks it at the midpoint, so the
    # centred rank average is exactly zero regardless of raw magnitude.
    assert scores["AAA"].value == pytest.approx(0.0)


def test_empty_signal_mapping_is_rejected(store):
    with pytest.raises(ValueError, match="at least one signal"):
        run_backtest(store, {}, d("2026-01-01"), d("2026-02-28"))


# --- weighting scheme (Phase 5) ----------------------------------------


def test_weighting_defaults_to_equal_and_is_unchanged(store):
    """Every recorded Gate 0 number was produced under equal weighting."""
    a = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0)
    b = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0, weighting="equal")
    assert a.equity == b.equity and len(a.trades) == len(b.trades)


def test_invvol_weighting_runs_and_still_trades(store):
    r = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0, weighting="invvol")
    assert r.trades


def test_unknown_weighting_is_rejected(store):
    with pytest.raises(ValueError, match="weighting"):
        run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     weighting="magic")


def test_weigh_selects_before_pricing_volatility(store):
    """Vol is computed only for the names actually chosen.

    `realised_vols` costs one query per symbol. Pricing the whole universe each
    rebalance would be hundreds of queries to size ten positions.
    """
    from ghambla.backtest import weigh
    calls = {}
    import ghambla.backtest as bt
    real = bt.realised_vols

    def spy(store_, day, symbols, lookback=252):
        calls["symbols"] = list(symbols)
        return real(store_, day, symbols, lookback=lookback)

    bt.realised_vols = spy
    try:
        scores = {s: Score(value=1.0, confidence=1.0, rationale="x")
                  for s in ("AAA", "BBB", "CCC", "DDD")}
        weigh(scores, 2, "invvol", store, d("2026-01-15"), 252)
    finally:
        bt.realised_vols = real
    assert len(calls["symbols"]) == 2


# --- market-regime filter ----------------------------------------------


def test_regime_filter_is_off_by_default(store):
    a = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0)
    b = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0, regime_filter=False)
    assert a.equity == b.equity and len(a.trades) == len(b.trades)


def test_regime_filter_holds_cash_when_it_cannot_evaluate(store):
    """Fails closed: no benchmark history means no exposure.

    The fixture has no SPY at all, so the filter returns None every day. An
    unknown regime must not be read as a friendly one.
    """
    r = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0, regime_filter=True, regime_lookback=5)
    assert r.trades == []


def test_regime_filter_trades_when_the_benchmark_is_rising(store):
    from ghambla.store.store import Bar
    from ghambla.universe import BENCHMARK
    day = d("2025-11-01")
    bars = []
    for i in range(120):
        px = 100.0 * 1.002 ** i
        bars.append(Bar(BENCHMARK, day, px, px, px, px, px, 1000))
        day += dt.timedelta(days=1)
    store.upsert_bars(bars)
    r = run_backtest(store, AlwaysBuy(), d("2026-01-01"), d("2026-02-28"),
                     initial_cash=10_000.0, regime_filter=True, regime_lookback=20)
    assert r.trades
