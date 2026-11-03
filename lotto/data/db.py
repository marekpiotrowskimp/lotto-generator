"""Magazyn SQLite."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from lotto import config
from lotto.data.validate import Draw

SCHEMA = """
CREATE TABLE IF NOT EXISTS draws (
    draw_no   INTEGER PRIMARY KEY,
    date      TEXT NOT NULL,
    n1 INTEGER NOT NULL, n2 INTEGER NOT NULL, n3 INTEGER NOT NULL,
    n4 INTEGER NOT NULL, n5 INTEGER NOT NULL, n6 INTEGER NOT NULL,
    -- kolejność wypadania kul (NULL, gdy nieznana)
    o1 INTEGER, o2 INTEGER, o3 INTEGER, o4 INTEGER, o5 INTEGER, o6 INTEGER,
    source    TEXT NOT NULL,
    imported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS draws_date ON draws(date);

-- Wygrane i liczba zwycięzców w każdym stopniu (tier = liczba trafień 3..6).
CREATE TABLE IF NOT EXISTS prizes (
    draw_no INTEGER NOT NULL REFERENCES draws(draw_no),
    tier    INTEGER NOT NULL CHECK (tier BETWEEN 3 AND 6),
    winners INTEGER NOT NULL,
    amount  REAL NOT NULL,
    PRIMARY KEY (draw_no, tier)
);

CREATE TABLE IF NOT EXISTS draw_meta (
    draw_no    INTEGER PRIMARY KEY REFERENCES draws(draw_no),
    total_pool REAL,
    jackpot    REAL,
    sales      REAL
);

-- Losowania, w których źródła się różnią.
CREATE TABLE IF NOT EXISTS disputes (
    draw_no   INTEGER NOT NULL,
    source    TEXT NOT NULL,
    date      TEXT NOT NULL,
    numbers   TEXT NOT NULL,
    noted_at  TEXT NOT NULL,
    PRIMARY KEY (draw_no, source)
);

-- Stan pobierania wygranych dla losowania: ok / no_data (strona bez wygranych) / error.
CREATE TABLE IF NOT EXISTS prize_fetch (
    draw_no    INTEGER PRIMARY KEY REFERENCES draws(draw_no),
    status     TEXT NOT NULL,
    message    TEXT,
    fetched_at TEXT NOT NULL
);

-- Proste wartości klucz-wartość, np. zapowiadana kumulacja.
CREATE TABLE IF NOT EXISTS state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    source  TEXT NOT NULL,
    added   INTEGER NOT NULL,
    status  TEXT NOT NULL,
    message TEXT
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or config.db_path()
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: synchronizacja w tle używa własnego połączenia,
    # ale serwer może przekazywać połączenia między wątkami puli.
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def upsert_draws(conn: sqlite3.Connection, draws: list[Draw], source: str) -> int:
    """Wstawia nowe losowania, a istniejącym uzupełnia kolejność. Zwraca liczbę nowych."""
    before = count_draws(conn)
    now = _now()
    conn.executemany(
        """INSERT INTO draws (draw_no, date, n1, n2, n3, n4, n5, n6,
                              o1, o2, o3, o4, o5, o6, source, imported_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(draw_no) DO UPDATE SET
               o1 = COALESCE(draws.o1, excluded.o1), o2 = COALESCE(draws.o2, excluded.o2),
               o3 = COALESCE(draws.o3, excluded.o3), o4 = COALESCE(draws.o4, excluded.o4),
               o5 = COALESCE(draws.o5, excluded.o5), o6 = COALESCE(draws.o6, excluded.o6)""",
        [
            (d.draw_no, d.date.isoformat(), *d.numbers, *(d.order or (None,) * 6), source, now)
            for d in draws
        ],
    )
    conn.commit()
    return count_draws(conn) - before


def record_disputes(conn: sqlite3.Connection, diffs: list[dict], source: str) -> None:
    now = _now()
    conn.executemany(
        "INSERT OR REPLACE INTO disputes (draw_no, source, date, numbers, noted_at) VALUES (?, ?, ?, ?, ?)",
        [
            (x["draw_no"], source, x["secondary"][0].isoformat(),
             ",".join(map(str, x["secondary"][1])), now)
            for x in diffs
        ],
    )
    conn.commit()


def log_sync(conn: sqlite3.Connection, source: str, added: int, status: str, message: str = "") -> None:
    conn.execute(
        "INSERT INTO sync_log (ts, source, added, status, message) VALUES (?, ?, ?, ?, ?)",
        (_now(), source, added, status, message),
    )
    conn.commit()


def count_draws(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]


def last_draw(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM draws ORDER BY draw_no DESC LIMIT 1").fetchone()


def load_draws(conn: sqlite3.Connection, since: date | None = None) -> list[Draw]:
    q = "SELECT * FROM draws"
    args: tuple = ()
    if since:
        q += " WHERE date >= ?"
        args = (since.isoformat(),)
    return [_row_to_draw(r) for r in conn.execute(q + " ORDER BY draw_no", args)]


def _row_to_draw(r: sqlite3.Row) -> Draw:
    order = tuple(r[f"o{i}"] for i in range(1, 7))
    return Draw(
        r["draw_no"], date.fromisoformat(r["date"]),
        tuple(r[f"n{i}"] for i in range(1, 7)),
        None if order[0] is None else order,
    )


def get_draw(conn: sqlite3.Connection, draw_no: int) -> Draw | None:
    r = conn.execute("SELECT * FROM draws WHERE draw_no = ?", (draw_no,)).fetchone()
    return _row_to_draw(r) if r else None


def save_prizes(conn: sqlite3.Connection, draw_no: int, prizes: dict[int, tuple[int, float]],
                total_pool: float | None) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO prizes (draw_no, tier, winners, amount) VALUES (?, ?, ?, ?)",
        [(draw_no, tier, w, a) for tier, (w, a) in prizes.items()],
    )
    conn.execute(
        """INSERT INTO draw_meta (draw_no, total_pool) VALUES (?, ?)
           ON CONFLICT(draw_no) DO UPDATE SET total_pool = excluded.total_pool""",
        (draw_no, total_pool),
    )
    conn.commit()


def mark_prize_fetch(conn: sqlite3.Connection, draw_no: int, status: str, message: str = "") -> None:
    conn.execute(
        "INSERT OR REPLACE INTO prize_fetch (draw_no, status, message, fetched_at) VALUES (?, ?, ?, ?)",
        (draw_no, status, message, _now()),
    )
    conn.commit()


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO state (key, value, updated_at) VALUES (?, ?, ?)", (key, value, _now()))
    conn.commit()


def get_state(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    return conn.execute("SELECT value, updated_at FROM state WHERE key = ?", (key,)).fetchone()
