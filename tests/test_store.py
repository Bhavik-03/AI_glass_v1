import sqlite3

from server import config, store

REAL_CONNECT = sqlite3.connect


def table_names(path) -> set[str]:
    con = REAL_CONNECT(path)
    try:
        rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return {r[0] for r in rows}
    finally:
        con.close()


def test_fr8_init_creates_folder_and_tables(monkeypatch, tmp_path):
    """init() creates the missing parent folder and the notes and reminders tables; safe to call twice."""
    path = tmp_path / "sub" / "x.db"
    monkeypatch.setattr("server.config.DB_PATH", path)
    assert not path.parent.exists()

    store.init()
    store.init()

    assert path.parent.is_dir()
    assert {"notes", "reminders"} <= table_names(path)


def test_fr8_add_note_returns_note_and_stores_row(db):
    """add_note returns {id, text, created_at} and the notes table has one new row with that text and time."""
    created = "2026-10-09T14:00:00+05:30"

    note = store.add_note("buy milk", created)

    assert set(note) == {"id", "text", "created_at"}
    assert note["text"] == "buy milk"
    assert note["created_at"] == created
    con = REAL_CONNECT(db)
    try:
        rows = con.execute("SELECT * FROM notes").fetchall()
    finally:
        con.close()
    assert len(rows) == 1
    assert "buy milk" in rows[0]
    assert created in rows[0]


def test_fr8_list_notes_empty(db):
    """list_notes returns an empty list when there are no notes."""
    assert store.list_notes() == []


def test_fr8_list_notes_newest_first(db):
    """list_notes returns every note, newest first."""
    store.add_note("first", "2026-10-09T10:00:00+05:30")
    store.add_note("second", "2026-10-09T11:00:00+05:30")
    store.add_note("third", "2026-10-09T12:00:00+05:30")

    notes = store.list_notes()

    assert [n["text"] for n in notes] == ["third", "second", "first"]
    assert set(notes[0]) == {"id", "text", "created_at"}


def test_fr8_list_notes_ties_newest_inserted_first(db):
    """Notes with the same creation time come back newest-inserted first."""
    same = "2026-10-09T10:00:00+05:30"
    store.add_note("a", same)
    store.add_note("b", same)
    store.add_note("c", same)

    assert [n["text"] for n in store.list_notes()] == ["c", "b", "a"]


def test_fr8_each_call_opens_own_connection_with_busy_timeout(db, monkeypatch):
    """Each call opens its own short connection with the busy timeout config.DB_TIMEOUT_S (5 s)."""
    assert config.DB_TIMEOUT_S == 5
    timeouts = []

    def recording_connect(*args, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        return REAL_CONNECT(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", recording_connect)

    store.add_note("x", "2026-10-09T10:00:00+05:30")
    assert len(timeouts) == 1
    store.list_notes()
    assert len(timeouts) == 2
    store.list_notes()
    assert len(timeouts) == 3
    assert timeouts == [config.DB_TIMEOUT_S] * 3


def reminder_rows(path) -> list[tuple]:
    con = REAL_CONNECT(path)
    try:
        return con.execute("SELECT id, text, due_at, status FROM reminders").fetchall()
    finally:
        con.close()


def status_of(path, reminder_id: int) -> str:
    con = REAL_CONNECT(path)
    try:
        row = con.execute("SELECT status FROM reminders WHERE id = ?", (reminder_id,))
        return row.fetchone()[0]
    finally:
        con.close()


def set_status(path, reminder_id: int, status: str) -> None:
    con = REAL_CONNECT(path)
    try:
        with con:
            con.execute(
                "UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id)
            )
    finally:
        con.close()


CREATED = "2026-10-09T14:00:00+05:30"
DUE_A = "2026-10-09T15:00:00+05:30"
DUE_B = "2026-10-09T16:00:00+05:30"
DUE_C = "2026-10-09T17:00:00+05:30"


def test_fr9_add_reminder_stores_one_pending_row_and_returns_it(db):
    """add_reminder stores exactly one pending row and returns {id, text, due_at}."""
    reminder = store.add_reminder("call mom", DUE_A, CREATED)

    assert set(reminder) == {"id", "text", "due_at"}
    assert reminder["text"] == "call mom"
    assert reminder["due_at"] == DUE_A
    rows = reminder_rows(db)
    assert rows == [(reminder["id"], "call mom", DUE_A, store.PENDING)]


def test_fr9_list_pending_ordered_by_due_at(db):
    """list_pending returns pending reminders ordered by due_at, whatever the insert order."""
    store.add_reminder("late", DUE_C, CREATED)
    store.add_reminder("early", DUE_A, CREATED)
    store.add_reminder("middle", DUE_B, CREATED)

    pending = store.list_pending()

    assert [r["text"] for r in pending] == ["early", "middle", "late"]
    assert all(set(r) == {"id", "text", "due_at"} for r in pending)


def test_fr9_list_pending_ties_by_id(db):
    """Pending reminders with the same due_at come back in id order."""
    first = store.add_reminder("first", DUE_A, CREATED)
    second = store.add_reminder("second", DUE_A, CREATED)

    assert [r["id"] for r in store.list_pending()] == [first["id"], second["id"]]


def test_fr9_list_pending_excludes_cancelled(db):
    """list_pending leaves out cancelled reminders."""
    keep = store.add_reminder("keep", DUE_A, CREATED)
    drop = store.add_reminder("drop", DUE_B, CREATED)
    store.cancel(drop["id"])

    assert store.list_pending() == [keep]


def test_fr9_list_pending_excludes_delivered(db):
    """list_pending leaves out delivered reminders."""
    keep = store.add_reminder("keep", DUE_B, CREATED)
    done = store.add_reminder("done", DUE_A, CREATED)
    set_status(db, done["id"], store.DELIVERED)

    assert store.list_pending() == [keep]


def test_fr9_list_pending_empty(db):
    """list_pending returns an empty list when nothing is pending."""
    assert store.list_pending() == []


def test_fr9_cancel_sets_cancelled_and_returns_reminder(db):
    """cancel sets the status to cancelled and returns the reminder as {id, text, due_at}."""
    added = store.add_reminder("call mom", DUE_A, CREATED)

    result = store.cancel(added["id"])

    assert result == added
    assert status_of(db, added["id"]) == store.CANCELLED


def test_fr9_cancel_unknown_id_returns_none(db):
    """cancel of an unknown id returns None."""
    assert store.cancel(999) is None


def test_fr9_cancel_already_cancelled_returns_none(db):
    """cancel of an already cancelled reminder returns None."""
    added = store.add_reminder("call mom", DUE_A, CREATED)
    store.cancel(added["id"])

    assert store.cancel(added["id"]) is None
    assert status_of(db, added["id"]) == store.CANCELLED


def test_fr9_cancel_delivered_returns_none_and_keeps_status(db):
    """cancel of a delivered reminder returns None and leaves it delivered."""
    added = store.add_reminder("call mom", DUE_A, CREATED)
    set_status(db, added["id"], store.DELIVERED)

    assert store.cancel(added["id"]) is None
    assert status_of(db, added["id"]) == store.DELIVERED
