import sqlite3
from contextlib import closing, contextmanager

from server import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    due_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
);
"""


@contextmanager
def _connect():
    """One short connection per call: FastAPI runs handlers in a thread pool."""
    with closing(sqlite3.connect(config.DB_PATH, timeout=config.DB_TIMEOUT_S)) as con:
        con.row_factory = sqlite3.Row
        with con:  # commits on success, rolls back on error
            yield con


def init() -> None:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as con:
        con.executescript(SCHEMA)


def add_note(text: str, created_at: str) -> dict:
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO notes (text, created_at) VALUES (?, ?)", (text, created_at)
        )
    return {"id": cur.lastrowid, "text": text, "created_at": created_at}


def list_notes() -> list[dict]:
    with _connect() as con:
        rows = con.execute(
            "SELECT id, text, created_at FROM notes ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [dict(row) for row in rows]
