import sqlite3
from contextlib import closing, contextmanager

from server import config

PENDING = "pending"
DELIVERED = "delivered"
CANCELLED = "cancelled"

SCHEMA = f"""
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
    status TEXT NOT NULL DEFAULT '{PENDING}'
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


def add_reminder(text: str, due_at: str, created_at: str) -> dict:
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO reminders (text, due_at, created_at, status) VALUES (?, ?, ?, ?)",
            (text, due_at, created_at, PENDING),
        )
    return {"id": cur.lastrowid, "text": text, "due_at": due_at}


def list_pending() -> list[dict]:
    with _connect() as con:
        rows = con.execute(
            "SELECT id, text, due_at FROM reminders WHERE status = ? ORDER BY due_at, id",
            (PENDING,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_due(now: str) -> list[dict]:
    with _connect() as con:
        rows = con.execute(
            "SELECT id, text, due_at FROM reminders"
            " WHERE status = ? AND due_at <= ? ORDER BY due_at, id",
            (PENDING, now),
        ).fetchall()
    return [dict(row) for row in rows]


def _fetch(con: sqlite3.Connection, reminder_id: int) -> dict | None:
    row = con.execute(
        "SELECT id, text, due_at FROM reminders WHERE id = ?", (reminder_id,)
    ).fetchone()
    return dict(row) if row else None


def get(reminder_id: int) -> dict | None:
    with _connect() as con:
        return _fetch(con, reminder_id)


def _move_pending(con: sqlite3.Connection, reminder_id: int, status: str) -> int:
    """One conditional UPDATE, so a concurrent change can't slip in between check and write."""
    cur = con.execute(
        "UPDATE reminders SET status = ? WHERE id = ? AND status = ?",
        (status, reminder_id, PENDING),
    )
    return cur.rowcount


def cancel(reminder_id: int) -> dict | None:
    """Cancel a pending reminder; None if the id is unknown or not pending."""
    with _connect() as con:
        if _move_pending(con, reminder_id, CANCELLED):
            return _fetch(con, reminder_id)
    return None


def ack(reminder_id: int) -> dict | None:
    """Mark a pending reminder delivered; any existing reminder is returned, None if unknown."""
    with _connect() as con:
        _move_pending(con, reminder_id, DELIVERED)
        return _fetch(con, reminder_id)
