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
