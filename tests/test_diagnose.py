"""Is the drawdown problem actually correlation, or was that just a story?"""
import pytest

from ghambla.diagnose import average_pairwise_correlation, diversification_ratio


def test_identical_series_are_perfectly_correlated():
    s = {"A": [0.01, -0.02, 0.03, 0.00], "B": [0.02, -0.04, 0.06, 0.00]}
    assert average_pairwise_correlation(s) == pytest.approx(1.0)


def test_mirrored_series_are_perfectly_anticorrelated():
    s = {"A": [0.01, -0.02, 0.03, -0.01], "B": [-0.01, 0.02, -0.03, 0.01]}
    assert average_pairwise_correlation(s) == pytest.approx(-1.0)


def test_average_is_over_all_distinct_pairs():
    """Three series: A~B = +1, A~C = -1, B~C = -1, so the mean is -1/3."""
    a = [0.01, -0.02, 0.03, -0.01]
    s = {"A": a, "B": [2 * x for x in a], "C": [-x for x in a]}
    assert average_pairwise_correlation(s) == pytest.approx(-1 / 3)


def test_fewer_than_two_series_is_none():
    assert average_pairwise_correlation({"A": [0.01, 0.02, 0.03]}) is None
    assert average_pairwise_correlation({}) is None


def test_flat_series_is_skipped_not_counted_as_correlated():
    """A constant series has zero variance, so its correlation is undefined.

    Counting it as 0.0 would drag the average toward 'diversified' purely
    because a name did not move, which is the opposite of the truth.
    """
    a = [0.01, -0.02, 0.03, -0.01]
    s = {"A": a, "B": [2 * x for x in a], "FLAT": [0.0, 0.0, 0.0, 0.0]}
    assert average_pairwise_correlation(s) == pytest.approx(1.0)


def test_all_flat_is_none():
    assert average_pairwise_correlation({"A": [0.0] * 5, "B": [0.0] * 5}) is None


def test_perfectly_correlated_book_has_no_diversification():
    """Ratio 1.0 means the book is one bet wearing several tickers."""
    weights = {"A": 0.5, "B": 0.5}
    vols = {"A": 0.20, "B": 0.30}
    # Perfectly correlated: portfolio vol == weighted average vol == 0.25
    assert diversification_ratio(weights, vols, 0.25) == pytest.approx(1.0)


def test_diversification_shows_as_a_ratio_above_one():
    weights = {"A": 0.5, "B": 0.5}
    vols = {"A": 0.20, "B": 0.20}
    assert diversification_ratio(weights, vols, 0.10) == pytest.approx(2.0)


def test_zero_portfolio_vol_is_none_not_infinity():
    assert diversification_ratio({"A": 1.0}, {"A": 0.2}, 0.0) is None


def test_missing_vol_is_none_rather_than_a_wrong_number():
    """Silently treating an absent vol as zero would understate concentration."""
    assert diversification_ratio({"A": 0.5, "B": 0.5}, {"A": 0.2}, 0.15) is None


def test_nan_portfolio_vol_is_none_not_nan():
    """NaN fails a `<= 0` guard and would propagate silently through a report.

    Raised by the cold review, which correctly noted the spec did not cover it.
    """
    assert diversification_ratio({"A": 1.0}, {"A": 0.2}, float("nan")) is None


def test_nan_inputs_do_not_produce_a_nan_ratio():
    assert diversification_ratio({"A": 1.0}, {"A": float("nan")}, 0.2) is None
