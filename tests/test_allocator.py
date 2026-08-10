

# --- tied values must not become an alphabetical bias -------------------


def test_tied_values_share_a_rank_rather_than_spreading_alphabetically():
    """Identical scores must not be ordered by ticker.

    `_ranks` sorted on (value, symbol), so a signal that ties every name spread
    them evenly from 0.0 to 1.0 by alphabet — ZTS scored 1.00 and AAPL 0.00 on
    identical data. The news signal ties constantly (most headlines are equally
    (ir)relevant), so this silently made the rank average a popularity contest
    for late-alphabet tickers, and it decided what got bought.
    """
    from ghambla.allocator import _ranks
    from ghambla.signals.base import Score
    tied = {s: Score(value=1.0, confidence=1.0, rationale="x")
            for s in ("AAPL", "BBB", "MSFT", "WST", "ZTS")}
    ranks = _ranks(tied)
    assert len(set(ranks.values())) == 1, f"ties must share one rank, got {ranks}"


def test_partial_ties_get_the_midrank_of_their_group():
    """Standard midrank handling: a tied group takes the average of the
    positions it spans, so the ordering of distinct values is preserved."""
    from ghambla.allocator import _ranks
    from ghambla.signals.base import Score
    s = lambda v: Score(value=v, confidence=1.0, rationale="x")
    ranks = _ranks({"LOW": s(0.0), "MID_A": s(0.5), "MID_B": s(0.5), "HIGH": s(1.0)})
    assert ranks["LOW"] < ranks["MID_A"] == ranks["MID_B"] < ranks["HIGH"]
    assert ranks["LOW"] == 0.0 and ranks["HIGH"] == 1.0


def test_distinct_values_are_unaffected():
    """The fix must not disturb the ordinary case."""
    from ghambla.allocator import _ranks
    from ghambla.signals.base import Score
    s = lambda v: Score(value=v, confidence=1.0, rationale="x")
    ranks = _ranks({"A": s(0.1), "B": s(0.2), "C": s(0.3)})
    assert ranks["A"] == 0.0 and ranks["B"] == 0.5 and ranks["C"] == 1.0
