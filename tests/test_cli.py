import datetime as dt

from ghambla.cli import main
from ghambla.store.store import Bar, FeatureStore


def d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _seed(db_path, n_days=400):
    """A tiny two-name market with enough history for the 252-day lookback."""
    s = FeatureStore(db_path)
    day = d("2025-01-01")
    bars = []
    for i in range(n_days):
        bars.append(Bar("AAA", day, 100.0 + i, 100.0 + i, 100.0 + i, 100.0 + i, 100.0 + i, 1000))
        bars.append(Bar("SPY", day, 50.0 + i * 0.5, 50.0 + i * 0.5, 50.0 + i * 0.5,
                        50.0 + i * 0.5, 50.0 + i * 0.5, 1000))
        day += dt.timedelta(days=1)
    s.upsert_bars(bars)
    s.set_universe(d("2024-12-01"), ["AAA"])
    s.close()
    return day - dt.timedelta(days=1)


def test_backtest_without_a_database_exits_nonzero(tmp_path, capsys):
    code = main(["--db", str(tmp_path / "nope.db"), "backtest"])
    assert code == 1
    assert "ingest" in capsys.readouterr().err


def test_backtest_with_no_data_in_range_exits_nonzero(tmp_path, capsys):
    db = tmp_path / "m.db"
    _seed(db)
    code = main(["--db", str(db), "backtest", "--start", "2010-01-01", "--end", "2010-12-31"])
    assert code == 1
    assert "No data in range" in capsys.readouterr().err


def test_backtest_prints_a_gate_verdict(tmp_path, capsys):
    db = tmp_path / "m.db"
    last = _seed(db)
    code = main(["--db", str(db), "backtest", "--start", "2026-01-01",
                 "--end", last.isoformat(), "--top-n", "1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Gate 0" in out
    assert "SPY" in out


def test_backtest_reports_the_dated_universe_size(tmp_path, capsys):
    db = tmp_path / "m.db"
    last = _seed(db)
    main(["--db", str(db), "backtest", "--start", "2026-01-01", "--end", last.isoformat()])
    assert "Universe on day one: 1 names" in capsys.readouterr().out


def test_evaluate_prints_a_walk_forward_verdict(tmp_path, capsys):
    db = tmp_path / "m.db"
    last = _seed(db)
    code = main(["--db", str(db), "evaluate", "--start", "2026-01-01",
                 "--end", last.isoformat(), "--windows", "2", "--holdout", "0.2"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Gate 0 (walk-forward)" in out
    assert "research" in out
    assert "holdout" in out


def test_evaluate_without_a_database_exits_nonzero(tmp_path, capsys):
    code = main(["--db", str(tmp_path / "nope.db"), "evaluate"])
    assert code == 1
    assert "ingest" in capsys.readouterr().err
