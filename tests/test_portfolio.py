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


# --- inverse-volatility weighting (Phase 5) ----------------------------

from ghambla.portfolio import inverse_vol_top_n


def test_selection_is_identical_to_equal_weight():
    """Weighting changes size, never which names are held."""
    scores = {"A": s(0.5), "B": s(0.1), "C": s(0.9), "D": s(-0.3)}
    vols = {"A": 0.2, "B": 0.2, "C": 0.2, "D": 0.2}
    assert ([t.symbol for t in inverse_vol_top_n(scores, 2, vols)]
            == [t.symbol for t in equal_weight_top_n(scores, 2)])


def test_calmer_names_get_more_weight():
    scores = {"A": s(0.9), "B": s(0.8)}
    # B is twice as volatile, so it should carry half A's weight.
    targets = {t.symbol: t.weight for t in inverse_vol_top_n(scores, 2, {"A": 0.1, "B": 0.2})}
    assert targets["A"] == pytest.approx(2 / 3)
    assert targets["B"] == pytest.approx(1 / 3)


def test_weights_sum_to_one():
    scores = {"A": s(0.9), "B": s(0.8), "C": s(0.7)}
    targets = inverse_vol_top_n(scores, 3, {"A": 0.1, "B": 0.25, "C": 0.4})
    assert sum(t.weight for t in targets) == pytest.approx(1.0)


def test_equal_vols_reduce_to_equal_weight():
    """The new scheme must degenerate to the old one, or comparison is unfair."""
    scores = {"A": s(0.9), "B": s(0.8), "C": s(0.7)}
    vols = {k: 0.3 for k in scores}
    assert all(t.weight == pytest.approx(1 / 3) for t in inverse_vol_top_n(scores, 3, vols))


def test_missing_vol_falls_back_to_the_median_of_the_chosen():
    """A name with no vol history must not be silently over- or under-weighted.

    Treating an unknown as zero vol would hand it an infinite weight; dropping
    it would concentrate the book into whatever remains. The median of the
    names actually chosen is the neutral assumption.
    """
    scores = {"A": s(0.9), "B": s(0.8), "C": s(0.7)}
    targets = {t.symbol: t.weight for t in
               inverse_vol_top_n(scores, 3, {"A": 0.1, "C": 0.3})}
    median_vol = 0.2  # median of {0.1, 0.3}
    expected_b = (1 / median_vol) / (1 / 0.1 + 1 / median_vol + 1 / 0.3)
    assert targets["B"] == pytest.approx(expected_b)


def test_non_positive_vol_is_treated_as_unknown():
    """A zero or negative vol is bad data, not a risk-free asset."""
    targets = {t.symbol: t.weight for t in
               inverse_vol_top_n({"A": s(0.9), "B": s(0.8)}, 2, {"A": 0.0, "B": 0.2})}
    assert targets["A"] == pytest.approx(0.5)
    assert targets["B"] == pytest.approx(0.5)


def test_no_vols_at_all_degrades_to_equal_weight():
    targets = inverse_vol_top_n({"A": s(0.9), "B": s(0.8)}, 2, {})
    assert all(t.weight == pytest.approx(0.5) for t in targets)


def test_empty_selection_yields_no_targets():
    assert inverse_vol_top_n({"A": s(-0.5)}, 3, {"A": 0.2}) == []


def test_rejects_non_positive_n_too():
    with pytest.raises(ValueError):
        inverse_vol_top_n({"A": s(0.5)}, 0, {"A": 0.2})
