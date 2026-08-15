"""Candlestick pattern tests.

Definitions are pre-registered in docs/analysis/gate0_candlestick_gap.md and
must not drift. These pin the geometry, the zero-range guard, and the sign of
every vote — a flipped vote turns "buy strength" into "buy weakness", a
different strategy that every ordering test would still pass.
"""
import datetime as dt

import pytest

from ghambla.signals.candles import (
    CandleSignal,
    bearish_engulfing,
    body,
    bullish_engulfing,
    bullish_marubozu,
    candle_range,
    doji,
    hammer,
    is_up,
    lower_shadow,
    pattern_votes,
    shooting_star,
    upper_shadow,
)
from ghambla.store.store import Bar, FeatureStore

DAY = dt.date(2026, 8, 3)


def bar(o, h, l, c, day=DAY, sym="AAA"):
    return Bar(symbol=sym, date=day, open=o, high=h, low=l, close=c,
               adj_close=c, volume=1000)


# --- geometry -------------------------------------------------------------

def test_body_is_absolute_so_direction_does_not_change_size():
    assert body(bar(10, 12, 9, 11)) == pytest.approx(1.0)
    assert body(bar(11, 12, 9, 10)) == pytest.approx(1.0)


def test_range_and_shadows():
    b = bar(10, 14, 8, 12)          # up bar: body 10..12
    assert candle_range(b) == pytest.approx(6.0)
    assert upper_shadow(b) == pytest.approx(2.0)   # 14 - 12
    assert lower_shadow(b) == pytest.approx(2.0)   # 10 - 8


def test_shadows_on_a_down_bar_use_the_body_not_the_close():
    b = bar(12, 14, 8, 10)          # down bar: body 10..12
    assert upper_shadow(b) == pytest.approx(2.0)   # 14 - 12
    assert lower_shadow(b) == pytest.approx(2.0)   # 10 - 8


def test_is_up_is_strict():
    assert is_up(bar(10, 11, 9, 11)) is True
    assert is_up(bar(10, 11, 9, 10)) is False      # doji-flat is not up


# --- the zero-range guard -------------------------------------------------

FLAT = bar(10, 10, 10, 10)


@pytest.mark.parametrize("detector", [bullish_marubozu, doji])
def test_single_bar_detectors_reject_a_zero_range_bar(detector):
    """A halted bar has no pattern, and dividing by its range is a crash."""
    assert detector(FLAT) is False


@pytest.mark.parametrize("detector", [bullish_engulfing, bearish_engulfing,
                                      hammer, shooting_star])
def test_two_bar_detectors_reject_a_zero_range_current_bar(detector):
    assert detector(bar(10, 12, 9, 11), FLAT) is False


def test_shooting_star_rejects_a_flat_bar_after_a_rise():
    """The prior bar must actually be lower, or the 'after a rise' condition
    rejects the bar for the wrong reason and the zero-range guard is never
    exercised. A flat bar has zero shadows and zero body, which satisfies
    'shadow >= 2 x body' trivially — only the guard stops it firing."""
    rising_prev = bar(9, 9.5, 8.5, 9)          # closes below the flat bar
    assert rising_prev.close < FLAT.close
    assert shooting_star(rising_prev, FLAT) is False


def test_hammer_rejects_a_flat_bar_after_a_decline():
    falling_prev = bar(12, 12.5, 11.5, 12)     # closes above the flat bar
    assert falling_prev.close > FLAT.close
    assert hammer(falling_prev, FLAT) is False


# --- patterns -------------------------------------------------------------

def test_bullish_engulfing_needs_an_up_bar_covering_a_down_bar():
    prev = bar(11, 11.5, 9.5, 10)       # down, body 10..11
    cur = bar(9.5, 12.5, 9.4, 11.5)     # up,   body 9.5..11.5 covers it
    assert bullish_engulfing(prev, cur) is True


def test_bullish_engulfing_rejects_a_body_that_does_not_cover():
    prev = bar(11, 11.5, 9.5, 10)
    cur = bar(10.2, 11.0, 10.1, 10.8)   # up but inside prev's body
    assert bullish_engulfing(prev, cur) is False


def test_bullish_engulfing_rejects_a_down_current_bar():
    prev = bar(11, 11.5, 9.5, 10)
    cur = bar(11.5, 12.0, 9.4, 9.5)     # covers, but is itself down
    assert bullish_engulfing(prev, cur) is False


def test_bearish_engulfing_is_the_mirror():
    prev = bar(10, 11.5, 9.5, 11)       # up,   body 10..11
    cur = bar(11.5, 12.0, 9.4, 9.5)     # down, body 9.5..11.5 covers it
    assert bearish_engulfing(prev, cur) is True
    assert bullish_engulfing(prev, cur) is False


def test_hammer_needs_a_long_lower_shadow_after_a_decline():
    prev = bar(12, 12.5, 11.5, 12)
    cur = bar(11.6, 11.7, 10.0, 11.5)   # body 0.1, lower shadow 1.6
    assert lower_shadow(cur) >= 2 * body(cur)
    assert hammer(prev, cur) is True


def test_hammer_is_rejected_when_it_does_not_follow_a_decline():
    prev = bar(10, 10.2, 9.8, 10.0)     # prev.close below cur.close
    cur = bar(11.6, 11.7, 10.0, 11.5)
    assert hammer(prev, cur) is False


def test_shooting_star_needs_a_long_upper_shadow_after_a_rise():
    prev = bar(10, 10.5, 9.5, 10)
    cur = bar(11.5, 13.2, 11.4, 11.6)   # body 0.1, upper shadow 1.6
    assert upper_shadow(cur) >= 2 * body(cur)
    assert shooting_star(prev, cur) is True


def test_marubozu_needs_a_dominant_up_body():
    assert bullish_marubozu(bar(10.0, 12.05, 9.95, 12.0)) is True
    assert bullish_marubozu(bar(12.0, 12.05, 9.95, 10.0)) is False  # down bar
    assert bullish_marubozu(bar(10.0, 14.0, 9.0, 11.0)) is False    # small body


def test_doji_is_a_tiny_body():
    assert doji(bar(10.0, 11.0, 9.0, 10.02)) is True
    assert doji(bar(10.0, 11.0, 9.0, 10.9)) is False


# --- votes ----------------------------------------------------------------

def test_a_bullish_pattern_votes_positive():
    prev = bar(11, 11.5, 9.5, 10)
    cur = bar(9.5, 12.5, 9.4, 11.5)
    assert pattern_votes(prev, cur) > 0


def test_a_bearish_pattern_votes_negative():
    prev = bar(10, 11.5, 9.5, 11)
    cur = bar(11.5, 12.0, 9.4, 9.5)
    assert pattern_votes(prev, cur) < 0


def test_a_doji_is_neutral_and_counts_neither_way():
    """Pre-registered as neutral. Counting it either way is a different rule."""
    prev = bar(10, 10.5, 9.5, 10)
    cur = bar(10.0, 11.0, 9.0, 10.02)
    assert doji(cur) is True
    assert pattern_votes(prev, cur) == 0


def test_nothing_firing_votes_zero():
    prev = bar(10, 10.5, 9.5, 10.2)
    cur = bar(10.2, 10.6, 10.0, 10.4)
    assert pattern_votes(prev, cur) == 0


# --- the signal -----------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    s = FeatureStore(tmp_path / "c.db")
    yield s
    s.close()


def seed(store, sym, bars_spec, start="2026-08-01"):
    day = dt.date.fromisoformat(start)
    rows = []
    for (o, h, l, c) in bars_spec:
        rows.append(bar(o, h, l, c, day=day, sym=sym))
        day += dt.timedelta(days=1)
    store.upsert_bars(rows)
    return day - dt.timedelta(days=1)


FLAT_SPEC = [(10, 10.5, 9.5, 10.2)] * 6
BULL_SPEC = [(10, 10.5, 9.5, 10.2),
             (11, 11.5, 9.5, 10.0),      # down
             (9.5, 12.5, 9.4, 11.5),     # bullish engulfing
             (9.5, 12.5, 9.4, 12.4),     # marubozu-ish
             (11.0, 13.0, 10.9, 12.9),   # marubozu-ish
             (11.0, 13.0, 10.9, 12.9)]


def test_a_bullish_sequence_outranks_a_quiet_one(store):
    last = seed(store, "BULL", BULL_SPEC)
    seed(store, "QUIET", FLAT_SPEC)
    scores = CandleSignal().score(store, last, ["BULL", "QUIET"])
    assert scores["BULL"].value > scores["QUIET"].value


def test_insufficient_history_abstains(store):
    last = seed(store, "SHORT", [(10, 11, 9, 10.5)])
    scores = CandleSignal().score(store, last, ["SHORT"])
    assert scores["SHORT"].confidence == 0.0


def test_unknown_symbol_abstains(store):
    seed(store, "BULL", BULL_SPEC)
    scores = CandleSignal().score(store, dt.date(2026, 8, 6), ["NOPE"])
    assert scores["NOPE"].confidence == 0.0


def test_score_is_normalised_by_the_lookback(store):
    """Value is votes per day, so it stays comparable across lookbacks."""
    last = seed(store, "BULL", BULL_SPEC)
    scores = CandleSignal(lookback_days=3).score(store, last, ["BULL"])
    assert -1.0 - 1e-9 <= scores["BULL"].value <= 3.0


def test_rationale_names_the_window(store):
    last = seed(store, "BULL", BULL_SPEC)
    r = CandleSignal().score(store, last, ["BULL"])["BULL"].rationale
    assert "candles" in r.lower()


def test_rejects_a_non_positive_lookback():
    with pytest.raises(ValueError):
        CandleSignal(lookback_days=0)


def test_signal_reads_only_point_in_time_bars(store):
    """A pattern from tomorrow must never score today."""
    seed(store, "BULL", BULL_SPEC)
    early = CandleSignal().score(store, dt.date(2026, 8, 2), ["BULL"])
    assert early["BULL"].confidence == 0.0
