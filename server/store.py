import re
import sqlite3
from contextlib import closing, contextmanager

from server import config

PENDING = "pending"
DELIVERED = "delivered"
CANCELLED = "cancelled"
NEW = "new"
RIGHT = "right"
WRONG = "wrong"
FACT = "fact"
PROJECT = "project"
PREFERENCE = "preference"
SESSION = "session"

# Dropped from a spoken question before it searches memories; negations are not listed.
STOPWORDS = frozenset(
    "a an the and or of to in on at for with is are was were be been am i my me it its this"  # noqa: SIM905
    " that as by from about into these those has have had do does did so than then there"
    " their what which who will would can could should may might just also very".split()
)

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
CREATE TABLE IF NOT EXISTS concepts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    summary TEXT NOT NULL,
    first_asked TEXT NOT NULL,
    last_asked TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT '{NEW}',
    last_quizzed TEXT
);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    type TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    text, content='', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts (rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts (memories_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
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


def add_memory(text: str, type: str, created_at: str) -> dict:
    """Store one key point; an item over `config.MEMORY_MAX_WORDS` words is rejected."""
    if len(text.split()) > config.MEMORY_MAX_WORDS:
        raise ValueError(f"memory is over {config.MEMORY_MAX_WORDS} words")
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO memories (text, type, created_at) VALUES (?, ?, ?)",
            (text, type, created_at),
        )
    return {"id": cur.lastrowid, "text": text, "type": type, "created_at": created_at}


def _match_query(question: str) -> str:
    """The question's content words as a quoted FTS5 OR query; '' when none are left."""
    words = re.findall(r"[a-z0-9]+", question.lower().replace("'", ""))
    return " OR ".join(f'"{w}"' for w in words if w not in STOPWORDS)


def _valid_bound(con: sqlite3.Connection, value: str | None) -> str | None:
    """`value` if SQLite can read it as a date or date-time, else None (no filter)."""
    if (
        value is None
        or con.execute("SELECT julianday(?)", (value,)).fetchone()[0] is None
    ):
        return None
    return value


def search_memories(
    query: str, k: int, since: str | None = None, until: str | None = None
) -> list[dict]:
    """The `k` memories that best match the question, best first.

    `since` (inclusive) and `until` (exclusive) are ISO 8601 and narrow the candidates by
    `created_at` before ranking; a bound SQLite cannot read is ignored.
    """
    match = _match_query(query)
    if not match:
        return []
    with _connect() as con:
        since, until = _valid_bound(con, since), _valid_bound(con, until)
        rows = con.execute(
            "SELECT m.id, m.text, m.type, m.created_at FROM memories_fts"
            " JOIN memories m ON m.id = memories_fts.rowid"
            " WHERE memories_fts MATCH ?"
            " AND (? IS NULL OR julianday(m.created_at) >= julianday(?))"
            " AND (? IS NULL OR julianday(m.created_at) < julianday(?))"
            " ORDER BY bm25(memories_fts), m.id DESC LIMIT ?",
            (match, since, since, until, until, k),
        ).fetchall()
    return [dict(row) for row in rows]


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


def log_concept(name: str, summary: str, now: str) -> dict:
    """Add a concept, or update the one whose name matches case-insensitively."""
    with _connect() as con:
        cur = con.execute(
            "UPDATE concepts SET summary = ?, last_asked = ? WHERE name = ?",
            (summary, now, name),
        )
        new = cur.rowcount == 0
        if new:
            con.execute(
                "INSERT INTO concepts (name, summary, first_asked, last_asked, status)"
                " VALUES (?, ?, ?, ?, ?)",
                (name, summary, now, now, NEW),
            )
        row = con.execute(
            "SELECT name, summary, status FROM concepts WHERE name = ?", (name,)
        ).fetchone()
    return {**dict(row), "new": new}


def concept_names() -> list[str]:
    with _connect() as con:
        rows = con.execute("SELECT name FROM concepts ORDER BY id").fetchall()
    return [row["name"] for row in rows]


def learned_since(since: str, limit: int) -> dict:
    """Count concepts first asked at or after `since`; names of the `limit` newest."""
    with _connect() as con:
        count = con.execute(
            "SELECT COUNT(*) FROM concepts WHERE first_asked >= ?", (since,)
        ).fetchone()[0]
        rows = con.execute(
            "SELECT name FROM concepts WHERE first_asked >= ?"
            " ORDER BY first_asked DESC, id DESC LIMIT ?",
            (since, limit),
        ).fetchall()
    return {"count": count, "names": [row["name"] for row in rows]}


def quiz_concepts(limit: int) -> list[dict]:
    """Concepts to quiz: status new, oldest first asked first, then wrong, oldest last quizzed first."""
    with _connect() as con:
        rows = con.execute(
            "SELECT name, summary, status FROM concepts WHERE status IN (?, ?)"
            " ORDER BY status = ? DESC, COALESCE(last_quizzed, first_asked), id LIMIT ?",
            (NEW, WRONG, NEW, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def set_quiz_result(name: str, correct: bool, now: str) -> None:
    with _connect() as con:
        con.execute(
            "UPDATE concepts SET status = ?, last_quizzed = ? WHERE name = ?",
            (RIGHT if correct else WRONG, now, name),
        )
