import pytest

from ghambla.portfolio import equal_weight_top_n
from ghambla.signals.base import Score


def s(v, conf=1.0):
    return Score(value=v, confidence=conf, rationale="test")


def test_picks_top_n_by_value():
    scores = {"A": s(0.5), "B": s(0.1), "C": s(0.9), "D": s(0.3)}
    targets = equal_weight_top_n(scores, n=2)
    assert [t.symbol for t in targets] == ["C", "A"]


def test_weights_are_equal_and_sum_to_one():
    scores = {"A": s(0.5), "B": s(0.4), "C": s(0.3), "D": s(0.2)}
    targets = equal_weight_top_n(scores, n=4)
    assert all(t.weight == pytest.approx(0.25) for t in targets)
    assert sum(t.weight for t in targets) == pytest.approx(1.0)


def test_zero_confidence_scores_are_excluded():
    # Abstention is not a bullish view, however high the value looks.
    scores = {"A": s(0.9, conf=0.0), "B": s(0.5), "C": s(0.4)}
    targets = equal_weight_top_n(scores, n=3)
    assert [t.symbol for t in targets] == ["B", "C"]


def test_negative_momentum_is_not_held_long_only():
    scores = {"A": s(-0.5), "B": s(0.2), "C": s(-0.1)}
    targets = equal_weight_top_n(scores, n=3)
    assert [t.symbol for t in targets] == ["B"]
    assert targets[0].weight == pytest.approx(1.0)


def test_no_eligible_symbols_yields_no_targets():
    assert equal_weight_top_n({"A": s(-0.5), "B": s(-0.2)}, n=3) == []


def test_fewer_eligible_than_n_still_sums_to_one():
    targets = equal_weight_top_n({"A": s(0.5), "B": s(0.2)}, n=5)
    assert sum(t.weight for t in targets) == pytest.approx(1.0)


def test_ties_break_alphabetically_for_determinism():
    targets = equal_weight_top_n({"B": s(0.5), "A": s(0.5)}, n=1)
    assert [t.symbol for t in targets] == ["A"]


def test_rejects_non_positive_n():
    with pytest.raises(ValueError):
        equal_weight_top_n({"A": s(0.5)}, n=0)
