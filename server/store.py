import re
import sqlite3
from contextlib import closing, contextmanager
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

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
REMINDER = "reminder"
NOTICE = "notice"

DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")

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
    status TEXT NOT NULL DEFAULT '{PENDING}',
    kind TEXT NOT NULL DEFAULT '{REMINDER}'
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
        # CREATE TABLE IF NOT EXISTS leaves a database made before v3 without `kind`.
        if "kind" not in {
            r["name"] for r in con.execute("PRAGMA table_info(reminders)")
        }:
            con.execute(
                f"ALTER TABLE reminders ADD COLUMN kind TEXT NOT NULL DEFAULT '{REMINDER}'"
            )


def too_long(text: str) -> bool:
    """Whether a memory text is over `config.MEMORY_MAX_WORDS` words: the one definition of the
    limit, used by the store's own check and by the session writer's."""
    return len(text.split()) > config.MEMORY_MAX_WORDS


def _check_length(text: str) -> None:
    if too_long(text):
        raise ValueError(f"memory is over {config.MEMORY_MAX_WORDS} words")


def add_memory(text: str, type: str, created_at: str) -> dict:
    """Store one key point; an item over `config.MEMORY_MAX_WORDS` words is rejected."""
    _check_length(text)
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO memories (text, type, created_at) VALUES (?, ?, ?)",
            (text, type, created_at),
        )
    return {"id": cur.lastrowid, "text": text, "type": type, "created_at": created_at}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower().replace("'", ""))


def _match_query(question: str) -> str:
    """The question's content words as a quoted FTS5 OR query; '' when none are left."""
    return " OR ".join(f'"{w}"' for w in _words(question) if w not in STOPWORDS)


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _content_stems(text: str) -> set[str]:
    """The stemmed content words of `text`: what find_same and forget_memory compare."""
    return {_stem(w) for w in _words(text) if w not in STOPWORDS}


def find_same(text: str) -> dict | None:
    """The stored memory that repeats `text` almost word for word, else None.

    A safety guard, not a deduplicator: Jaccard on stemmed content words at
    `config.MEMORY_SAME_THRESHOLD` merges near-verbatim repeats only. Paraphrases stay apart.
    """
    new = _content_stems(text)
    best, best_score = None, 0.0
    with _connect() as con:
        rows = con.execute("SELECT id, text, type, created_at FROM memories").fetchall()
    for row in rows:
        old = _content_stems(row["text"])
        score = len(new & old) / len(new | old) if new | old else 0.0
        if score >= config.MEMORY_SAME_THRESHOLD and score > best_score:
            best, best_score = dict(row), score
    return best


def judge_point(text: str, user_text: str, profile_text: str) -> dict:
    """Judge a point the session writer returned against what the user said and the profile.

    Compares content stems as `find_same` does. `user_text` is the user's turns only, never the
    assistant's; `profile_text` is the profile values, never the slot labels. The verdict is
    "ungrounded" when the point shares no stem with `user_text`, "known" when the profile covers
    `config.WRITER_KNOWN_SHARE` of it or `config.WRITER_LEAK_STEMS` of its stems are in the
    profile but not in `user_text`, else None. Also returns the two shares and the leaked
    stems (FR-39, FR-40). It checks words, not truth: see the known limits in design.md.
    """
    stems = _content_stems(text)
    said = _content_stems(user_text)
    known = _content_stems(profile_text)
    size = len(stems) or 1
    leak = sorted((stems & known) - said)
    grounded, share = len(stems & said) / size, len(stems & known) / size
    if not stems & said:
        verdict = "ungrounded"
    elif share >= config.WRITER_KNOWN_SHARE or len(leak) >= config.WRITER_LEAK_STEMS:
        verdict = "known"
    else:
        verdict = None
    return {"verdict": verdict, "grounded": grounded, "known": share, "leak": leak}


def forget_memory(query: str) -> dict:
    """Delete the one memory that contains every content word of `query`.

    Recall matches on any word, which is far too loose for a DELETE, so forgetting needs
    all of them (same stems as find_same). Returns {"deleted": item}, or {"candidates":
    [...]} with nothing deleted: empty when nothing matched, two or more when ambiguous.
    """
    wanted = _content_stems(query)
    with _connect() as con:
        rows = con.execute(
            "SELECT id, text, type, created_at FROM memories ORDER BY id"
        ).fetchall()
        matches = [
            dict(r) for r in rows if wanted and wanted <= _content_stems(r["text"])
        ]
        if len(matches) == 1:
            con.execute("DELETE FROM memories WHERE id = ?", (matches[0]["id"],))
            return {"deleted": matches[0]}
    return {"candidates": matches}


def wipe_memories() -> int:
    """Delete every memory and its index entries; notes, reminders and concepts stay.
    Returns how many were deleted (FR-35)."""
    with _connect() as con:
        return con.execute("DELETE FROM memories").rowcount


def remember(text: str, type: str, created_at: str) -> dict:
    """Store a key point unless a near-verbatim repeat is already stored.

    Returns the item and `new`: False with the existing item (unchanged) for a repeat.
    """
    _check_length(text)
    existing = find_same(text)
    if existing:
        return {**existing, "new": False}
    return {**add_memory(text, type, created_at), "new": True}


def _valid_bound(con: sqlite3.Connection, value: str | None) -> str | None:
    """`value` if SQLite can read it as a date-time, else None (no filter).

    SQLite reads a bare date as UTC midnight, so a date-only bound becomes midnight in
    `config.TIMEZONE` first.
    """
    if value is None:
        return None
    if DATE_ONLY.fullmatch(value):
        try:
            day = date.fromisoformat(value)
        except ValueError:
            return None
        value = datetime.combine(day, time.min, ZoneInfo(config.TIMEZONE)).isoformat()
    if con.execute("SELECT julianday(?)", (value,)).fetchone()[0] is None:
        return None
    return value


# The window of a memory query; the four parameters come from `_window`.
IN_WINDOW = (
    " AND (? IS NULL OR julianday(m.created_at) >= julianday(?))"
    " AND (? IS NULL OR julianday(m.created_at) < julianday(?))"
)
MATCHES = (
    " FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid"
    " WHERE memories_fts MATCH ?"
)


def _window(con: sqlite3.Connection, since: str | None, until: str | None) -> tuple:
    since, until = _valid_bound(con, since), _valid_bound(con, until)
    return since, since, until, until


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
        rows = con.execute(
            "SELECT m.id, m.text, m.type, m.created_at"
            + MATCHES
            + IN_WINDOW
            + " ORDER BY bm25(memories_fts), m.id DESC LIMIT ?",
            (match, *_window(con, since, until), k),
        ).fetchall()
    return [dict(row) for row in rows]


def count_matches(
    query: str, since: str | None = None, until: str | None = None
) -> int:
    """How many memories match the question in the window, however many are returned."""
    match = _match_query(query)
    if not match:
        return 0
    with _connect() as con:
        return con.execute(
            "SELECT COUNT(*)" + MATCHES + IN_WINDOW,
            (match, *_window(con, since, until)),
        ).fetchone()[0]


def recent_memories(
    k: int, since: str | None = None, until: str | None = None
) -> list[dict]:
    """The `k` newest memories in the window, newest first (compared as moments)."""
    with _connect() as con:
        rows = con.execute(
            "SELECT m.id, m.text, m.type, m.created_at FROM memories m WHERE 1 = 1"
            + IN_WINDOW
            + " ORDER BY julianday(m.created_at) DESC, m.id DESC LIMIT ?",
            (*_window(con, since, until), k),
        ).fetchall()
    return [dict(row) for row in rows]


def count_memories(since: str | None = None, until: str | None = None) -> int:
    """How many memories are in the window."""
    with _connect() as con:
        return con.execute(
            "SELECT COUNT(*) FROM memories m WHERE 1 = 1" + IN_WINDOW,
            _window(con, since, until),
        ).fetchone()[0]


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


def add_notice(text: str, now: str) -> dict:
    """Store a spoken notice, due now, that the reminder poll delivers (FR-39)."""
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO reminders (text, due_at, created_at, status, kind)"
            " VALUES (?, ?, ?, ?, ?)",
            (text, now, now, PENDING, NOTICE),
        )
    return {"id": cur.lastrowid, "text": text, "due_at": now}


def list_pending() -> list[dict]:
    """Pending reminders; a notice is not one."""
    with _connect() as con:
        rows = con.execute(
            "SELECT id, text, due_at FROM reminders"
            " WHERE status = ? AND kind = ? ORDER BY due_at, id",
            (PENDING, REMINDER),
        ).fetchall()
    return [dict(row) for row in rows]


def list_due(now: str) -> list[dict]:
    """Due reminders and notices alike: the poll delivers both."""
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
    """The reminder or notice, with its kind."""
    with _connect() as con:
        item = _fetch(con, reminder_id)
        if item:
            item["kind"] = con.execute(
                "SELECT kind FROM reminders WHERE id = ?", (reminder_id,)
            ).fetchone()["kind"]
        return item


def _move_pending(
    con: sqlite3.Connection, reminder_id: int, status: str, kind: str | None = None
) -> int:
    """One conditional UPDATE, so a concurrent change can't slip in between check and write.
    With `kind`, only a row of that kind moves."""
    cur = con.execute(
        "UPDATE reminders SET status = ? WHERE id = ? AND status = ?"
        " AND kind = COALESCE(?, kind)",
        (status, reminder_id, PENDING, kind),
    )
    return cur.rowcount


def cancel(reminder_id: int) -> dict | None:
    """Cancel a pending reminder; None if the id is unknown, not pending or a notice."""
    with _connect() as con:
        if _move_pending(con, reminder_id, CANCELLED, REMINDER):
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
