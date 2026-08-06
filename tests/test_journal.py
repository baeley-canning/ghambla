import datetime as dt

from ghambla.journal import DecisionRecord, Journal


def record(**kw):
    base = dict(
        as_of=dt.date(2026, 8, 5),
        cycle_started=dt.datetime(2026, 8, 5, 21, 30, tzinfo=dt.UTC),
        mode="paper",
        universe_size=503,
        signal_scores={"momentum_12_1": {"AAA": {"value": 0.4, "confidence": 1.0}}},
        allocator="rank_average",
        targets={"AAA": 0.5},
        risk_vetoes=[],
        orders=[{"symbol": "AAA", "side": "BUY", "shares": 5}],
        fills=[{"symbol": "AAA", "price": 100.0}],
        equity=10_000.0,
        cash=9_500.0,
        positions={"AAA": 5.0},
    )
    base.update(kw)
    return DecisionRecord(**base)


def test_append_and_read_back(tmp_path):
    j = Journal(tmp_path / "j.jsonl")
    j.append(record())
    rows = list(j.read())
    assert len(rows) == 1
    assert rows[0]["mode"] == "paper"
    assert rows[0]["as_of"] == "2026-08-05"


def test_appending_never_overwrites(tmp_path):
    j = Journal(tmp_path / "j.jsonl")
    j.append(record(equity=1.0))
    j.append(record(equity=2.0))
    j.append(record(equity=3.0))
    assert [r["equity"] for r in j.read()] == [1.0, 2.0, 3.0]
    assert j.count() == 3


def test_last_returns_the_most_recent(tmp_path):
    j = Journal(tmp_path / "j.jsonl")
    j.append(record(equity=1.0))
    j.append(record(equity=2.0))
    assert j.last()["equity"] == 2.0


def test_reading_a_missing_file_is_empty_not_an_error(tmp_path):
    assert list(Journal(tmp_path / "nope.jsonl").read()) == []
    assert Journal(tmp_path / "nope.jsonl").last() is None


def test_a_truncated_tail_does_not_destroy_earlier_records(tmp_path):
    """A crash mid-write must not make the whole history unreadable."""
    path = tmp_path / "j.jsonl"
    j = Journal(path)
    j.append(record(equity=1.0))
    j.append(record(equity=2.0))
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"equity": 3.0, "mode": "pap')  # interrupted
    assert [r["equity"] for r in j.read()] == [1.0, 2.0]


def test_the_rationale_survives_the_round_trip(tmp_path):
    """The journal exists to answer 'why did it buy that' later."""
    j = Journal(tmp_path / "j.jsonl")
    j.append(record(signal_scores={
        "momentum_12_1": {"AAA": {"value": 0.42, "rationale": "12-1 momentum +42.0%"}}}))
    got = j.last()["signal_scores"]["momentum_12_1"]["AAA"]
    assert got["rationale"] == "12-1 momentum +42.0%"


def test_vetoes_are_recorded(tmp_path):
    j = Journal(tmp_path / "j.jsonl")
    j.append(record(risk_vetoes=["AAA capped 60.0% -> 20.0%"]))
    assert j.last()["risk_vetoes"] == ["AAA capped 60.0% -> 20.0%"]


def test_directory_is_created_if_absent(tmp_path):
    j = Journal(tmp_path / "deep" / "nested" / "j.jsonl")
    j.append(record())
    assert j.count() == 1
