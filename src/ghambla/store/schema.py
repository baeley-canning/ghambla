"""SQLite DDL.

Every table storing a fact carries `knowable_at`: the date on which that fact
became knowable to a trader. All reads filter on it. This is the mechanism
that makes lookahead bias structurally impossible rather than merely
discouraged.
"""

BARS = """
CREATE TABLE IF NOT EXISTS bars (
    symbol      TEXT NOT NULL,
    date        TEXT NOT NULL,
    open        REAL NOT NULL,
    high        REAL NOT NULL,
    low         REAL NOT NULL,
    close       REAL NOT NULL,
    adj_close   REAL NOT NULL,
    volume      INTEGER NOT NULL,
    knowable_at TEXT NOT NULL,
    PRIMARY KEY (symbol, date)
);
"""

BARS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_bars_knowable
    ON bars (symbol, knowable_at);
"""

UNIVERSE = """
CREATE TABLE IF NOT EXISTS universe (
    effective   TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    knowable_at TEXT NOT NULL,
    PRIMARY KEY (effective, symbol)
);
"""

ALL = [BARS, BARS_INDEX, UNIVERSE]
