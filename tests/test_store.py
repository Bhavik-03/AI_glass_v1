import json
import sqlite3
from pathlib import Path

import pytest

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


NOW = "2026-10-09T16:00:00+05:30"


def test_fr12_list_due_includes_due_now_and_past_oldest_first(db):
    """list_due returns pending reminders with due_at <= now (equal included), oldest first."""
    store.add_reminder("now", NOW, CREATED)
    store.add_reminder("older", DUE_A, CREATED)
    store.add_reminder("oldest", "2026-10-09T14:30:00+05:30", CREATED)

    due = store.list_due(NOW)

    assert [r["text"] for r in due] == ["oldest", "older", "now"]
    assert all(set(r) == {"id", "text", "due_at"} for r in due)
    assert due[-1]["due_at"] == NOW


def test_fr12_list_due_excludes_future(db):
    """list_due never lists a reminder whose due_at is after now."""
    due = store.add_reminder("due", DUE_A, CREATED)
    store.add_reminder("future", DUE_C, CREATED)

    assert store.list_due(NOW) == [due]


def test_fr12_list_due_excludes_delivered(db):
    """list_due never lists a delivered reminder."""
    keep = store.add_reminder("keep", DUE_B, CREATED)
    done = store.add_reminder("done", DUE_A, CREATED)
    set_status(db, done["id"], store.DELIVERED)

    assert store.list_due(NOW) == [keep]


def test_fr12_list_due_excludes_cancelled(db):
    """list_due never lists a cancelled reminder."""
    keep = store.add_reminder("keep", DUE_B, CREATED)
    drop = store.add_reminder("drop", DUE_A, CREATED)
    store.cancel(drop["id"])

    assert store.list_due(NOW) == [keep]


def test_fr12_list_due_empty(db):
    """list_due returns an empty list when nothing is due."""
    assert store.list_due(NOW) == []


def test_fr12_list_due_does_not_change_status(db):
    """Polling again without an ack returns the same reminders; list_due changes no status."""
    a = store.add_reminder("a", DUE_A, CREATED)
    b = store.add_reminder("b", DUE_B, CREATED)
    before = reminder_rows(db)

    first = store.list_due(NOW)
    second = store.list_due(NOW)

    assert first == second == [a, b]
    assert reminder_rows(db) == before
    assert status_of(db, a["id"]) == store.PENDING
    assert status_of(db, b["id"]) == store.PENDING


def test_fr12_get_returns_reminder(db):
    """get returns {id, text, due_at} and its kind for an existing reminder."""
    added = store.add_reminder("call mom", DUE_A, CREATED)

    assert store.get(added["id"]) == {**added, "kind": "reminder"}


def test_fr12_get_unknown_id_returns_none(db):
    """get of an unknown id returns None."""
    assert store.get(999) is None


def test_fr14_ack_pending_returns_reminder_and_marks_delivered(db):
    """ack of a pending reminder returns it, marks it delivered, and it leaves list_due."""
    added = store.add_reminder("call mom", DUE_A, CREATED)
    assert store.list_due(NOW) == [added]

    assert store.ack(added["id"]) == added

    assert status_of(db, added["id"]) == store.DELIVERED
    assert store.list_due(NOW) == []


def test_fr14_ack_twice_returns_reminder_both_times(db):
    """Acking again returns the reminder again and the status stays delivered."""
    added = store.add_reminder("call mom", DUE_A, CREATED)

    assert store.ack(added["id"]) == added
    assert store.ack(added["id"]) == added
    assert status_of(db, added["id"]) == store.DELIVERED


def test_fr14_ack_cancelled_returns_reminder_and_keeps_cancelled(db):
    """ack of a cancelled reminder returns it but leaves it cancelled, not delivered."""
    added = store.add_reminder("call mom", DUE_A, CREATED)
    store.cancel(added["id"])

    assert store.ack(added["id"]) == added
    assert status_of(db, added["id"]) == store.CANCELLED


def test_fr14_ack_unknown_id_returns_none(db):
    """ack of an unknown id returns None."""
    assert store.ack(999) is None


T1 = "2026-10-09T10:00:00+05:30"
T2 = "2026-10-10T11:00:00+05:30"


def concept_rows(path) -> list[tuple]:
    con = REAL_CONNECT(path)
    try:
        return con.execute(
            "SELECT name, summary, status, first_asked, last_asked, last_quizzed"
            " FROM concepts"
        ).fetchall()
    finally:
        con.close()


def test_fr23_new_concept_adds_one_row_with_status_new(db):
    """A new concept adds one row: status new, first and last asked set to now, last quizzed empty."""
    result = store.log_concept("LoRA", "Low-rank adapters for fine-tuning", T1)

    assert result == {
        "name": "LoRA",
        "summary": "Low-rank adapters for fine-tuning",
        "status": "new",
        "new": True,
    }
    assert concept_rows(db) == [
        ("LoRA", "Low-rank adapters for fine-tuning", "new", T1, T1, None)
    ]


def test_fr23_same_name_other_case_updates_row_and_adds_none(db):
    """The same name in another case updates last_asked and the summary, keeps first_asked, adds no row."""
    store.log_concept("LoRA", "old summary", T1)

    result = store.log_concept("lora", "new summary", T2)

    assert result == {
        "name": "LoRA",
        "summary": "new summary",
        "status": "new",
        "new": False,
    }
    assert concept_rows(db) == [("LoRA", "new summary", "new", T1, T2, None)]


def test_fr23_repeat_keeps_status(db):
    """An update leaves the status unchanged."""
    store.log_concept("LoRA", "s", T1)
    con = REAL_CONNECT(db)
    try:
        with con:
            con.execute("UPDATE concepts SET status = 'wrong'")
    finally:
        con.close()

    result = store.log_concept("LORA", "s2", T2)

    assert result["status"] == "wrong"
    assert result["new"] is False
    assert concept_rows(db)[0][2] == "wrong"


def test_fr23_concept_names_lists_all_names(db):
    """concept_names lists the names of all logged concepts, one per concept."""
    store.log_concept("LoRA", "a", T1)
    store.log_concept("Attention", "b", T1)
    store.log_concept("lora", "c", T2)

    assert sorted(store.concept_names()) == ["Attention", "LoRA"]


def test_fr23_concept_names_empty(db):
    """concept_names returns an empty list when no concept is logged."""
    assert store.concept_names() == []


def test_fr23_init_creates_concepts_table(monkeypatch, tmp_path):
    """init() creates the concepts table in the database."""
    path = tmp_path / "c.db"
    monkeypatch.setattr("server.config.DB_PATH", path)

    store.init()

    assert "concepts" in table_names(path)


def test_fr25_learned_since_counts_all_and_limits_names_newest_first(db):
    """learned_since counts every concept first asked at or after since, and lists the `limit` newest names, newest first."""
    for day in (3, 1, 5, 2, 4, 6):
        store.log_concept(f"c{day}", "s", f"2026-10-0{day}T10:00:00+05:30")
    store.log_concept("old", "s", "2026-09-01T10:00:00+05:30")

    result = store.learned_since("2026-10-02T10:00:00+05:30", 3)

    assert result == {"count": 5, "names": ["c6", "c5", "c4"]}


def test_fr25_learned_since_ignores_last_asked(db):
    """The window uses first_asked: a concept asked again recently but first asked before since is not counted."""
    store.log_concept("LoRA", "s", "2026-09-01T10:00:00+05:30")
    store.log_concept("lora", "s2", "2026-10-09T10:00:00+05:30")

    assert store.learned_since("2026-10-03T10:00:00+05:30", 5) == {
        "count": 0,
        "names": [],
    }


def test_fr25_learned_since_empty(db):
    """With no concepts, learned_since returns count 0 and no names."""
    assert store.learned_since("2026-10-03T10:00:00+05:30", 5) == {
        "count": 0,
        "names": [],
    }


def day(n: int) -> str:
    return f"2026-10-{n:02d}T10:00:00+05:30"


def names_of(concepts: list[dict]) -> list[str]:
    return [c["name"] for c in concepts]


def test_fr24_max_concepts_is_three():
    """A quiz picks up to config.QUIZ_MAX_CONCEPTS concepts, which is 3."""
    assert config.QUIZ_MAX_CONCEPTS == 3


def test_fr24_four_new_one_wrong_returns_three_oldest_new_in_order(db):
    """With 4 new and 1 wrong concept, the 3 oldest new ones come back, oldest first_asked first."""
    store.log_concept("wrongone", "w", day(1))
    store.set_quiz_result("wrongone", False, day(2))
    for n, name in ((6, "n6"), (3, "n3"), (5, "n5"), (4, "n4")):
        store.log_concept(name, f"summary {name}", day(n))

    result = store.quiz_concepts(config.QUIZ_MAX_CONCEPTS)

    assert names_of(result) == ["n3", "n4", "n5"]
    assert all(set(c) == {"name", "summary", "status"} for c in result)
    assert all(c["status"] == "new" for c in result)
    assert result[0]["summary"] == "summary n3"


def test_fr24_new_ties_broken_by_id(db):
    """New concepts with the same first_asked come back in id (insert) order."""
    for name in ("first", "second", "third"):
        store.log_concept(name, "s", T1)

    assert names_of(store.quiz_concepts(3)) == ["first", "second", "third"]


def test_fr24_new_come_before_wrong_when_room(db):
    """Status new is listed before status wrong when the limit leaves room for both."""
    store.log_concept("old", "s", day(1))
    store.set_quiz_result("old", False, day(2))
    store.log_concept("fresh", "s", day(5))

    result = store.quiz_concepts(3)

    assert names_of(result) == ["fresh", "old"]
    assert [c["status"] for c in result] == ["new", "wrong"]


def test_fr24_only_wrong_oldest_last_quizzed_first(db):
    """With only wrong concepts, the one quizzed longest ago comes first."""
    # first_asked runs opposite to last_quizzed, so ordering by first_asked would fail.
    for name, asked in (("a", 3), ("b", 2), ("c", 1)):
        store.log_concept(name, "s", day(asked))
    store.set_quiz_result("a", False, day(9))
    store.set_quiz_result("b", False, day(4))
    store.set_quiz_result("c", False, day(6))

    assert names_of(store.quiz_concepts(3)) == ["b", "c", "a"]


def test_fr24_right_concept_is_not_picked_again(db):
    """A concept set right is never returned by quiz_concepts."""
    store.log_concept("LoRA", "s", T1)

    store.set_quiz_result("LoRA", True, T2)

    assert store.quiz_concepts(3) == []


def test_fr24_wrong_concept_is_picked_again(db):
    """A concept set wrong is returned by a later quiz_concepts call with status wrong."""
    store.log_concept("LoRA", "s", T1)

    store.set_quiz_result("LoRA", False, T2)

    assert store.quiz_concepts(3) == [
        {"name": "LoRA", "summary": "s", "status": "wrong"}
    ]


def test_fr24_set_quiz_result_sets_status_and_last_quizzed_keeps_rows(db):
    """set_quiz_result sets status and last_quizzed to now, matches the name case-insensitively and deletes nothing."""
    store.log_concept("LoRA", "s", T1)
    store.log_concept("Attention", "t", T1)

    store.set_quiz_result("lora", True, T2)
    rows = {r[0]: r for r in concept_rows(db)}
    assert len(rows) == 2
    assert rows["LoRA"][2] == "right"
    assert rows["LoRA"][5] == T2
    assert rows["Attention"][2] == "new"
    assert rows["Attention"][5] is None

    store.set_quiz_result("LORA", False, "2026-10-11T09:00:00+05:30")
    rows = {r[0]: r for r in concept_rows(db)}
    assert len(rows) == 2
    assert rows["LoRA"][2] == "wrong"
    assert rows["LoRA"][5] == "2026-10-11T09:00:00+05:30"


def test_fr24_fewer_concepts_than_limit_returns_all_eligible(db):
    """With fewer eligible concepts than the limit, all of them are returned."""
    store.log_concept("a", "s", day(1))
    store.log_concept("b", "s", day(2))
    store.log_concept("done", "s", day(3))
    store.set_quiz_result("done", True, day(4))

    assert names_of(store.quiz_concepts(3)) == ["a", "b"]


def test_fr24_limit_caps_result(db):
    """quiz_concepts never returns more than limit concepts."""
    for n in range(1, 6):
        store.log_concept(f"c{n}", "s", day(n))

    assert names_of(store.quiz_concepts(2)) == ["c1", "c2"]


def test_fr24_no_eligible_concepts_returns_empty(db):
    """With no concepts at all, quiz_concepts returns an empty list."""
    assert store.quiz_concepts(3) == []


def traced_statements(monkeypatch, call) -> list[str]:
    statements: list[str] = []

    def tracing_connect(*args, **kwargs):
        con = REAL_CONNECT(*args, **kwargs)
        con.set_trace_callback(lambda sql: statements.append(sql.strip()))
        return con

    monkeypatch.setattr(sqlite3, "connect", tracing_connect)
    call()
    return statements


def assert_single_update_without_prior_select(statements: list[str]) -> None:
    kinds = [s.upper() for s in statements]
    updates = [i for i, s in enumerate(kinds) if s.startswith("UPDATE")]
    assert len(updates) == 1, statements
    assert not any(s.startswith("SELECT") for s in kinds[: updates[0]]), statements


def test_fr14_cancel_and_ack_run_one_update_and_no_select_before_it(db, monkeypatch):
    """cancel and ack each run exactly one UPDATE and no SELECT before it in the same call."""
    to_cancel = store.add_reminder("cancel me", DUE_A, CREATED)
    to_ack = store.add_reminder("ack me", DUE_B, CREATED)

    cancel_sql = traced_statements(monkeypatch, lambda: store.cancel(to_cancel["id"]))
    ack_sql = traced_statements(monkeypatch, lambda: store.ack(to_ack["id"]))

    assert_single_update_without_prior_select(cancel_sql)
    assert_single_update_without_prior_select(ack_sql)


WORDS_12 = " ".join(f"w{i}" for i in range(12))
WORDS_13 = " ".join(f"w{i}" for i in range(13))
MEM_TIME = "2026-10-20T09:00:00+05:30"


def memory_rows(path) -> list[tuple]:
    con = REAL_CONNECT(path)
    try:
        return con.execute("SELECT * FROM memories").fetchall()
    finally:
        con.close()


def test_fr32_init_creates_memories_table(db):
    """A memories table is created at startup."""
    assert "memories" in table_names(db)


def test_fr32_memory_max_words_is_12_in_config():
    """MEMORY_MAX_WORDS (12) comes from config."""
    assert config.MEMORY_MAX_WORDS == 12


def test_fr32_add_memory_sets_all_four_fields(db):
    """add_memory stores a row with id, text, type and created_at all set."""
    mem = store.add_memory("I prefer short answers", store.PREFERENCE, MEM_TIME)

    assert set(mem) == {"id", "text", "type", "created_at"}
    assert mem["id"] is not None
    assert mem["text"] == "I prefer short answers"
    assert mem["type"] == "preference"
    assert mem["created_at"] == MEM_TIME
    rows = memory_rows(db)
    assert len(rows) == 1
    assert "I prefer short answers" in rows[0]
    assert "preference" in rows[0]
    assert MEM_TIME in rows[0]
    assert mem["id"] in rows[0]


def test_fr32_type_constants():
    """The four types are fact, project, preference and session."""
    assert store.FACT == "fact"
    assert store.PROJECT == "project"
    assert store.PREFERENCE == "preference"
    assert store.SESSION == "session"


def test_fr32_twelve_word_item_is_accepted(db):
    """An item of exactly 12 words is accepted and stored."""
    mem = store.add_memory(WORDS_12, store.FACT, MEM_TIME)

    assert mem["text"] == WORDS_12
    assert len(memory_rows(db)) == 1


def test_fr32_thirteen_word_item_is_rejected_before_storage(db):
    """An item over the word limit raises ValueError naming the limit, and nothing is stored."""
    with pytest.raises(ValueError, match="12"):
        store.add_memory(WORDS_13, store.FACT, MEM_TIME)

    assert memory_rows(db) == []


def test_fr32_word_limit_is_read_from_config(db, monkeypatch):
    """The word limit is read from config.MEMORY_MAX_WORDS, not hard-coded."""
    monkeypatch.setattr("server.config.MEMORY_MAX_WORDS", 3)

    store.add_memory("one two three", store.FACT, MEM_TIME)
    with pytest.raises(ValueError, match="3"):
        store.add_memory("one two three four", store.FACT, MEM_TIME)

    assert len(memory_rows(db)) == 1


def test_fr32_memories_survive_restart(db):
    """The memories table and its rows survive a restart (init() again on the same database)."""
    store.add_memory("I study operating systems", store.PROJECT, MEM_TIME)

    store.init()

    rows = memory_rows(db)
    assert len(rows) == 1
    assert "I study operating systems" in rows[0]


def add_mems(*texts: str) -> list[dict]:
    return [store.add_memory(t, store.FACT, MEM_TIME) for t in texts]


def test_fr37_fts_table_exists_after_init(db):
    """An FTS5 index over memories.text exists after init()."""
    assert "memories_fts" in table_names(db)


def test_fr37_inserted_item_is_searchable_immediately(db):
    """An item added with add_memory is found by search_memories (index synced on insert)."""
    mem = store.add_memory("We discussed annotation tools", store.PROJECT, MEM_TIME)

    found = store.search_memories("annotation", 5)

    assert [m["id"] for m in found] == [mem["id"]]


def index_rowids(path, word: str) -> list[int]:
    """Rowids the FTS5 index itself holds for a word, without joining memories."""
    con = REAL_CONNECT(path)
    try:
        rows = con.execute(
            "SELECT rowid FROM memories_fts WHERE memories_fts MATCH ?", (f'"{word}"',)
        )
        return sorted(r[0] for r in rows)
    finally:
        con.close()


def test_fr37_delete_from_memories_empties_the_index(db):
    """DELETE FROM memories removes the rows from the index itself, not only from search."""
    first, second = add_mems("We discussed annotation tools", "I like annotation work")
    assert index_rowids(db, "annotation") == [first["id"], second["id"]]

    con = REAL_CONNECT(db)
    try:
        con.execute("DELETE FROM memories")
        con.commit()
    finally:
        con.close()

    assert index_rowids(db, "annotation") == []
    assert store.search_memories("annotation", 5) == []


def test_fr37_returns_at_most_k_items(db):
    """search_memories returns at most k items."""
    add_mems(*[f"annotation note number {n}" for n in range(6)])

    assert len(store.search_memories("annotation", 5)) == 5
    assert len(store.search_memories("annotation", 2)) == 2


def test_fr37_best_match_first(db):
    """An item matching two query words ranks before an item matching one."""
    two, one = add_mems(
        "annotation guidelines for the dataset",
        "annotation was discussed briefly",
    )

    found = store.search_memories("annotation dataset", 5)

    assert [m["id"] for m in found] == [two["id"], one["id"]]


def test_fr37_spoken_question_finds_item_with_other_words(db):
    """A question with words not in the item still returns the item containing 'annotation'."""
    target, *_ = add_mems(
        "Annotation guidelines are due on Friday",
        "My cat is called Biscuit",
        "I study operating systems at night",
        "Prefer short spoken answers",
    )

    found = store.search_memories("what did we discuss about annotation", 5)

    assert [m["id"] for m in found] == [target["id"]]


def test_fr37_stemmed_word_matches(db):
    """Word forms match through stemming ('annotations' finds 'annotation')."""
    mem, *_ = add_mems("Annotation guidelines are due on Friday", "My cat is Biscuit")

    found = store.search_memories("annotations", 5)

    assert [m["id"] for m in found] == [mem["id"]]


@pytest.mark.parametrize(
    "query",
    [
        'what\'s the "annotation" plan',
        "fine-tuning -x (y) AND OR NOT NEAR*",
        '"',
        "'",
        "*",
    ],
)
def test_fr37_syntax_characters_do_not_raise(db, query):
    """A question with FTS5 syntax characters (quotes, apostrophes, hyphens) does not raise."""
    add_mems("The annotation plan and fine-tuning notes")

    result = store.search_memories(query, 5)

    assert isinstance(result, list)


def test_fr37_question_with_quotes_still_matches(db):
    """Quotes and apostrophes around real words are ignored, the words still match."""
    mem, *_ = add_mems("The annotation plan is ready", "My cat is Biscuit")

    found = store.search_memories('what\'s the "annotation" plan', 5)

    assert [m["id"] for m in found] == [mem["id"]]


@pytest.mark.parametrize(
    "query", ['"', "'", "*", "", "what did we about", "AND OR NOT"]
)
def test_fr37_only_syntax_or_stopwords_returns_empty(db, query):
    """A query with no usable words returns []."""
    add_mems("The annotation plan is ready")

    assert store.search_memories(query, 5) == []


def test_fr37_no_match_returns_empty(db):
    """A question matching nothing returns []."""
    add_mems("The annotation plan is ready")

    assert store.search_memories("quantum chromodynamics", 5) == []


def test_fr37_each_item_has_four_fields(db):
    """Each returned item has id, text, type and created_at."""
    mem = store.add_memory("The annotation plan is ready", store.PROJECT, MEM_TIME)

    found = store.search_memories("annotation", 5)

    assert found == [
        {
            "id": mem["id"],
            "text": "The annotation plan is ready",
            "type": "project",
            "created_at": MEM_TIME,
        }
    ]


def add_at(text: str, created_at: str) -> dict:
    return store.add_memory(text, store.FACT, created_at)


def found_ids(query: str, k: int = 10, **window) -> list[int]:
    return sorted(m["id"] for m in store.search_memories(query, k, **window))


def test_fr38_since_excludes_item_before_and_keeps_item_inside(db):
    """since drops an item created before it and keeps one created inside the window."""
    add_at("annotation notes from August", "2026-08-20T10:00:00+05:30")
    inside = add_at("annotation notes from September", "2026-09-15T10:00:00+05:30")

    assert found_ids("annotation", since="2026-09-01") == [inside["id"]]


def test_fr38_until_excludes_item_after_and_keeps_item_inside(db):
    """until drops an item created after it and keeps one created inside the window."""
    inside = add_at("annotation notes from September", "2026-09-15T10:00:00+05:30")
    add_at("annotation notes from October", "2026-10-10T10:00:00+05:30")

    assert found_ids("annotation", until="2026-10-01") == [inside["id"]]


def test_fr38_both_bounds_return_only_item_inside_window(db):
    """With since and until, only the item inside the window is returned."""
    add_at("annotation notes from August", "2026-08-20T10:00:00+05:30")
    inside = add_at("annotation notes from September", "2026-09-15T10:00:00+05:30")
    add_at("annotation notes from October", "2026-10-10T10:00:00+05:30")

    assert found_ids("annotation", since="2026-09-01", until="2026-10-01") == [
        inside["id"]
    ]


def test_fr38_since_is_inclusive(db):
    """An item created exactly at since is included."""
    exact = add_at("annotation at the boundary", "2026-09-01T00:00:00+05:30")
    add_at("annotation just before", "2026-08-31T23:59:59+05:30")

    assert found_ids("annotation", since="2026-09-01T00:00:00+05:30") == [exact["id"]]


def test_fr38_until_is_exclusive(db):
    """An item created exactly at until is excluded; one just before is included."""
    before = add_at("annotation just before", "2026-09-30T23:59:59+05:30")
    add_at("annotation at the boundary", "2026-10-01T00:00:00+05:30")

    assert found_ids("annotation", until="2026-10-01T00:00:00+05:30") == [before["id"]]


def test_fr38_no_time_returns_both_items(db):
    """The same question with no since and until returns both items."""
    a = add_at("annotation notes from August", "2026-08-20T10:00:00+05:30")
    b = add_at("annotation notes from October", "2026-10-10T10:00:00+05:30")

    assert found_ids("annotation") == sorted([a["id"], b["id"]])


def test_fr38_filter_applies_before_ranking_and_k(db):
    """Outside items that rank higher cannot crowd the inside items out of the top k."""
    outside = [
        add_at("annotation dataset guidelines review", f"2026-08-0{n}T10:00:00+05:30")
        for n in range(1, 5)
    ]
    inside = [
        add_at("annotation was mentioned", "2026-09-10T10:00:00+05:30"),
        add_at("annotation came up again", "2026-09-12T10:00:00+05:30"),
    ]
    query = "annotation dataset guidelines review"
    unfiltered = {m["id"] for m in store.search_memories(query, 2)}
    assert unfiltered <= {o["id"] for o in outside}

    found = store.search_memories(query, 2, since="2026-09-01", until="2026-10-01")

    assert sorted(m["id"] for m in found) == sorted(i["id"] for i in inside)


@pytest.mark.parametrize("bad", ["last week", ""])
def test_fr38_unparseable_since_means_no_filter(db, bad):
    """An unparseable since is ignored: same results as no filter, not no results."""
    a = add_at("annotation notes from August", "2026-08-20T10:00:00+05:30")
    b = add_at("annotation notes from October", "2026-10-10T10:00:00+05:30")

    assert found_ids("annotation", since=bad) == sorted([a["id"], b["id"]])


@pytest.mark.parametrize("bad", ["next month", ""])
def test_fr38_unparseable_until_means_no_filter(db, bad):
    """An unparseable until is ignored: same results as no filter, not no results."""
    a = add_at("annotation notes from August", "2026-08-20T10:00:00+05:30")
    b = add_at("annotation notes from October", "2026-10-10T10:00:00+05:30")

    assert found_ids("annotation", until=bad) == sorted([a["id"], b["id"]])


def test_fr38_good_since_with_bad_until_applies_only_since(db):
    """A bad until is ignored while a good since still filters."""
    add_at("annotation notes from August", "2026-08-20T10:00:00+05:30")
    late = add_at("annotation notes from October", "2026-10-10T10:00:00+05:30")

    assert found_ids("annotation", since="2026-09-01", until="soon") == [late["id"]]


def test_fr38_good_until_with_bad_since_applies_only_until(db):
    """A bad since is ignored while a good until still filters."""
    early = add_at("annotation notes from August", "2026-08-20T10:00:00+05:30")
    add_at("annotation notes from October", "2026-10-10T10:00:00+05:30")

    assert found_ids("annotation", since="last week", until="2026-09-01") == [
        early["id"]
    ]


def test_fr38_bounds_with_other_offset_compare_as_same_moment(db):
    """A Z bound equals the same moment in +05:30: 2026-09-01T00:00:00Z is 05:30 IST."""
    before = add_at("annotation before the moment", "2026-09-01T05:29:59+05:30")
    exact = add_at("annotation at the moment", "2026-09-01T05:30:00+05:30")

    assert found_ids("annotation", since="2026-09-01T00:00:00Z") == [exact["id"]]
    assert found_ids("annotation", until="2026-09-01T00:00:00Z") == [before["id"]]


def test_fr40_threshold_config_is_point_nine():
    """MEMORY_SAME_THRESHOLD is 0.9 in config."""
    assert config.MEMORY_SAME_THRESHOLD == 0.9


def test_fr40_find_same_none_on_empty_store(db):
    """find_same returns None when the store is empty."""
    assert store.find_same("LoRA fine-tuning") is None


def test_fr40_find_same_finds_reordered_inflected_repeat(db):
    """A repeat with the same content words in another order is found."""
    [first] = add_mems("Annotation project deadline is in March")
    found = store.find_same("The deadline for the annotation project is March")
    assert found is not None
    assert found["id"] == first["id"]


def test_fr40_find_same_returns_stored_item_unchanged(db):
    """find_same returns the stored item with its original text and created_at."""
    store.add_memory("Studying LoRA fine-tuning", store.FACT, MEM_TIME)
    found = store.find_same("I am studying LoRA fine tuning")
    assert found["text"] == "Studying LoRA fine-tuning"
    assert found["created_at"] == MEM_TIME
    assert found["type"] == store.FACT
    assert set(found) == {"id", "text", "type", "created_at"}


def test_fr40_find_same_none_for_unrelated_topic(db):
    """'LoRA fine-tuning' stored: 'attention in transformers' is not found."""
    add_mems("LoRA fine-tuning")
    assert store.find_same("attention in transformers") is None


def test_fr40_find_same_none_for_opposites(db):
    """Opposite points that differ by one word are not the same."""
    add_mems("Prefers answers with code examples")
    assert store.find_same("Prefers answers without code examples") is None


def test_fr40_find_same_none_for_one_word_change(db):
    """Changing one content word (Rust to Go) is not a repeat."""
    add_mems("Wants to learn Rust this year")
    assert store.find_same("Wants to learn Go this year") is None


def test_fr40_find_same_uses_config_threshold_lower(db, monkeypatch):
    """A lower MEMORY_SAME_THRESHOLD makes a partly similar pair match."""
    add_mems("Wants to learn Rust this year")
    assert store.find_same("Wants to learn Go this year") is None
    monkeypatch.setattr(config, "MEMORY_SAME_THRESHOLD", 0.5)
    assert store.find_same("Wants to learn Go this year") is not None


def test_fr40_find_same_uses_config_threshold_above_one(db, monkeypatch):
    """With the threshold above 1, even identical text does not match."""
    add_mems("LoRA fine-tuning")
    monkeypatch.setattr(config, "MEMORY_SAME_THRESHOLD", 1.1)
    assert store.find_same("LoRA fine-tuning") is None


def test_fr40_find_same_picks_best_scoring(db, monkeypatch):
    """When several stored items match, the best-scoring one wins."""
    monkeypatch.setattr(config, "MEMORY_SAME_THRESHOLD", 0.5)
    _, second = add_mems(
        "Project deadline March annotation",
        "Project deadline March annotation review team",
    )
    found = store.find_same("Project deadline March annotation review team")
    assert found["id"] == second["id"]


def test_fr40_remember_first_add_is_new(db):
    """remember on an empty store adds a row and returns new True."""
    item = store.remember("LoRA fine-tuning", store.FACT, MEM_TIME)
    assert item["new"] is True
    assert item["text"] == "LoRA fine-tuning"
    assert item["type"] == store.FACT
    assert item["created_at"] == MEM_TIME
    assert len(memory_rows(db)) == 1


def test_fr40_remember_near_verbatim_repeat_adds_no_row(db):
    """A near-verbatim repeat adds no row, keeps the stored item, returns new False."""
    first = store.remember("Studying LoRA fine-tuning", store.FACT, MEM_TIME)
    before = memory_rows(db)
    later = "2026-10-21T09:00:00+05:30"
    again = store.remember("I am studying LoRA fine tuning", store.FACT, later)
    assert again["new"] is False
    assert again["id"] == first["id"]
    assert again["text"] == "Studying LoRA fine-tuning"
    assert again["created_at"] == MEM_TIME
    assert memory_rows(db) == before


def test_fr40_remember_unrelated_point_adds_row_and_leaves_first(db):
    """'LoRA fine-tuning' stored: adding 'attention in transformers' makes a new row."""
    store.remember("LoRA fine-tuning", store.FACT, MEM_TIME)
    before = memory_rows(db)
    item = store.remember("attention in transformers", store.FACT, MEM_TIME)
    assert item["new"] is True
    after = memory_rows(db)
    assert len(after) == 2
    assert after[0] == before[0]


def test_fr40_remember_paraphrase_with_new_content_words_adds_row(db):
    """A paraphrase that changes content words adds a row."""
    store.remember("Prefers short answers", store.FACT, MEM_TIME)
    item = store.remember("Likes brief answers", store.FACT, MEM_TIME)
    assert item["new"] is True
    assert len(memory_rows(db)) == 2


def test_fr40_remember_over_word_limit_raises_even_if_match(db):
    """Text over the word limit raises ValueError even when it would match; nothing stored."""
    store.remember(WORDS_12, store.FACT, MEM_TIME)
    before = memory_rows(db)
    with pytest.raises(ValueError, match=str(config.MEMORY_MAX_WORDS)):
        store.remember(WORDS_13, store.FACT, MEM_TIME)
    assert memory_rows(db) == before


def test_fr38_date_only_since_is_local_midnight_includes_early_morning_item(db):
    """since='2026-09-01' is midnight IST, so an item at 02:00+05:30 on that day is returned."""
    early = add_at("annotation early morning", "2026-09-01T02:00:00+05:30")

    assert found_ids("annotation", since="2026-09-01") == [early["id"]]


def test_fr38_date_only_until_is_local_midnight_excludes_early_morning_item(db):
    """until='2026-09-01' is midnight IST, so an item at 02:00+05:30 on that day is excluded."""
    before = add_at("annotation previous evening", "2026-08-31T20:00:00+05:30")
    add_at("annotation early morning", "2026-09-01T02:00:00+05:30")

    assert found_ids("annotation", until="2026-09-01") == [before["id"]]


def test_fr38_date_only_since_excludes_last_second_of_previous_day(db):
    """An item at 2026-08-31T23:59:59+05:30 is excluded by since='2026-09-01'."""
    add_at("annotation last second", "2026-08-31T23:59:59+05:30")
    after = add_at("annotation first hour", "2026-09-01T01:00:00+05:30")

    assert found_ids("annotation", since="2026-09-01") == [after["id"]]


def test_fr38_date_only_until_includes_last_second_of_previous_day(db):
    """An item at 2026-08-31T23:59:59+05:30 is included by until='2026-09-01'."""
    last = add_at("annotation last second", "2026-08-31T23:59:59+05:30")
    add_at("annotation first hour", "2026-09-01T01:00:00+05:30")

    assert found_ids("annotation", until="2026-09-01") == [last["id"]]


def test_fr38_date_only_since_is_inclusive_at_local_midnight(db):
    """An item exactly at 2026-09-01T00:00:00+05:30 is included by since='2026-09-01'."""
    exact = add_at("annotation at midnight", "2026-09-01T00:00:00+05:30")

    assert found_ids("annotation", since="2026-09-01") == [exact["id"]]


def test_fr38_date_only_until_is_exclusive_at_local_midnight(db):
    """An item exactly at 2026-09-01T00:00:00+05:30 is excluded by until='2026-09-01'."""
    before = add_at("annotation before midnight", "2026-08-31T23:59:59+05:30")
    add_at("annotation at midnight", "2026-09-01T00:00:00+05:30")

    assert found_ids("annotation", until="2026-09-01") == [before["id"]]


def test_fr38_date_only_window_covers_whole_local_day(db):
    """since='2026-09-01', until='2026-09-02' returns the whole local day and nothing outside it."""
    add_at("annotation day before", "2026-08-31T23:59:59+05:30")
    early = add_at("annotation early", "2026-09-01T02:00:00+05:30")
    late = add_at("annotation late", "2026-09-01T23:30:00+05:30")
    add_at("annotation next day", "2026-09-02T00:00:00+05:30")

    assert found_ids("annotation", since="2026-09-01", until="2026-09-02") == sorted(
        [early["id"], late["id"]]
    )


def test_fr38_bound_with_time_and_offset_is_unchanged(db):
    """A bound that already carries a time and offset is compared as written."""
    add_at("annotation at two", "2026-09-01T02:00:00+05:30")
    three = add_at("annotation at three", "2026-09-01T03:00:00+05:30")

    assert found_ids("annotation", since="2026-09-01T03:00:00+05:30") == [three["id"]]


def test_fr38_z_bound_still_compares_as_same_moment(db):
    """A 'Z' bound is not shifted: 2026-08-31T20:30:00Z is 2026-09-01T02:00:00+05:30."""
    add_at("annotation before", "2026-09-01T01:59:59+05:30")
    exact = add_at("annotation exact", "2026-09-01T02:00:00+05:30")

    assert found_ids("annotation", since="2026-08-31T20:30:00Z") == [exact["id"]]


def test_fr38_date_only_bound_uses_configured_timezone(db, monkeypatch):
    """With config.TIMEZONE set to UTC, since='2026-09-01' is UTC midnight, so
    an item at 2026-09-01T02:00:00+05:30 (2026-08-31T20:30Z) is excluded."""
    monkeypatch.setattr(config, "TIMEZONE", "UTC")
    add_at("annotation early morning IST", "2026-09-01T02:00:00+05:30")
    later = add_at("annotation noon IST", "2026-09-01T12:00:00+05:30")

    assert found_ids("annotation", since="2026-09-01") == [later["id"]]


@pytest.mark.parametrize("bad", ["2026-13-45", "2026-02-30"])
def test_fr38_impossible_date_only_since_means_no_filter(db, bad):
    """An impossible date-only since is ignored, not raised and not 'no results'."""
    a = add_at("annotation notes from August", "2026-08-20T10:00:00+05:30")
    b = add_at("annotation notes from October", "2026-10-10T10:00:00+05:30")

    assert found_ids("annotation", since=bad) == sorted([a["id"], b["id"]])


@pytest.mark.parametrize("bad", ["2026-13-45", "2026-02-30"])
def test_fr38_impossible_date_only_until_means_no_filter(db, bad):
    """An impossible date-only until is ignored, not raised and not 'no results'."""
    a = add_at("annotation notes from August", "2026-08-20T10:00:00+05:30")
    b = add_at("annotation notes from October", "2026-10-10T10:00:00+05:30")

    assert found_ids("annotation", until=bad) == sorted([a["id"], b["id"]])


def mem_at(text: str, day: int, hour: int = 9) -> dict:
    return store.add_memory(
        text, store.FACT, f"2026-09-{day:02d}T{hour:02d}:00:00+05:30"
    )


def recent_ids(k: int, **window) -> list[int]:
    return [m["id"] for m in store.recent_memories(k, **window)]


def test_fr36_recall_and_list_max_are_five_in_config():
    """MEMORY_RECALL_MAX and MEMORY_LIST_MAX are both 5 in config."""
    assert config.MEMORY_RECALL_MAX == 5
    assert config.MEMORY_LIST_MAX == 5


def test_fr36_count_memories_empty_store_is_zero(db):
    """count_memories on an empty store is 0."""
    assert store.count_memories() == 0


def test_fr36_count_memories_counts_every_row_without_window(db):
    """With no window, count_memories counts all stored items, beyond any limit."""
    for n in range(1, 9):
        mem_at(f"separate point number {n}", n)

    assert store.count_memories() == 8


def test_fr36_count_memories_respects_window(db):
    """count_memories counts only items in the window: since inclusive, until exclusive."""
    for n in range(1, 9):
        mem_at(f"separate point number {n}", n)

    assert store.count_memories(since="2026-09-03", until="2026-09-06") == 3
    assert store.count_memories(since="2026-09-06") == 3
    assert store.count_memories(until="2026-09-03") == 2


def test_fr36_count_memories_unreadable_bound_is_ignored(db):
    """An unreadable since or until is ignored, not an empty result."""
    for n in range(1, 4):
        mem_at(f"separate point number {n}", n)

    assert store.count_memories(since="last week", until="soon") == 3


def test_fr36_recent_memories_empty_store_gives_empty_list(db):
    """recent_memories on an empty store returns []."""
    assert store.recent_memories(5) == []


def test_fr36_recent_memories_newest_first_and_limited_to_k(db):
    """recent_memories returns at most k items, newest first, whatever the insert order."""
    ids = {
        n: mem_at(f"separate point number {n}", n)["id"] for n in (4, 1, 7, 3, 6, 2, 5)
    }

    assert recent_ids(3) == [ids[7], ids[6], ids[5]]
    assert len(store.recent_memories(5)) == 5
    assert len(store.recent_memories(50)) == 7


def test_fr36_recent_memories_items_have_four_fields(db):
    """Each recent item has exactly id, text, type and created_at."""
    mem = store.add_memory("The annotation plan is ready", store.PROJECT, MEM_TIME)

    assert store.recent_memories(5) == [
        {
            "id": mem["id"],
            "text": "The annotation plan is ready",
            "type": "project",
            "created_at": MEM_TIME,
        }
    ]


def test_fr36_recent_memories_ties_higher_id_first(db):
    """Items with the same created_at come back higher id first."""
    a = mem_at("first point", 5)
    b = mem_at("second point", 5)
    c = mem_at("third point", 5)

    assert recent_ids(5) == [c["id"], b["id"], a["id"]]


def test_fr36_recent_memories_window_since_inclusive_until_exclusive(db):
    """recent_memories keeps items from since (inclusive) up to until (exclusive)."""
    before = add_at("point before", "2026-09-01T09:59:59+05:30")
    start = add_at("point at start", "2026-09-01T10:00:00+05:30")
    inside = add_at("point inside", "2026-09-02T10:00:00+05:30")
    add_at("point at end", "2026-09-03T10:00:00+05:30")

    got = recent_ids(
        5, since="2026-09-01T10:00:00+05:30", until="2026-09-03T10:00:00+05:30"
    )

    assert got == [inside["id"], start["id"]]
    assert before["id"] not in got


def test_fr36_recent_memories_date_only_bounds_are_local_midnight(db):
    """Date-only bounds mean local midnight: since='2026-09-01' keeps 02:00+05:30, until='2026-09-01' drops it."""
    late = add_at("previous evening", "2026-08-31T23:59:59+05:30")
    early = add_at("early morning", "2026-09-01T02:00:00+05:30")

    assert recent_ids(5, since="2026-09-01") == [early["id"]]
    assert recent_ids(5, until="2026-09-01") == [late["id"]]


def test_fr36_recent_memories_orders_mixed_offsets_as_instants(db):
    """Items stored with +05:30 and Z are ordered by moment in time, not by string."""
    # 2026-09-01T06:00:00Z is 11:30 IST: later than 10:00+05:30, but "T06" sorts before "T10".
    ist = add_at("kolkata item", "2026-09-01T10:00:00+05:30")
    utc = add_at("utc item", "2026-09-01T06:00:00Z")
    early_utc = add_at("early utc item", "2026-09-01T03:00:00Z")

    assert recent_ids(5) == [utc["id"], ist["id"], early_utc["id"]]


def test_fr36_recent_memories_window_compares_mixed_offsets_as_instants(db):
    """A Z item is placed in the window by its instant: 2026-09-01T06:00:00Z is 11:30 IST."""
    utc = add_at("utc item", "2026-09-01T06:00:00Z")
    add_at("kolkata item", "2026-09-01T10:00:00+05:30")

    got = recent_ids(5, since="2026-09-01T11:00:00+05:30")

    assert got == [utc["id"]]


def test_fr36_count_matches_counts_all_matches_beyond_any_limit(db):
    """count_matches counts every matching item (12), not just the top few."""
    add_mems(*[f"annotation note number {n}" for n in range(12)])
    add_mems(*[f"unrelated gardening item {n}" for n in range(8)])

    assert store.count_matches("annotation", since=None, until=None) == 12
    assert len(store.search_memories("annotation", 5)) == 5


def test_fr36_count_matches_uses_any_word_match(db):
    """count_matches counts an item that matches any content word of the question."""
    add_mems(
        "annotation guidelines for the dataset",
        "annotation was discussed briefly",
        "the dataset is large",
        "My cat is called Biscuit",
    )

    assert store.count_matches("annotation dataset") == 3


def test_fr36_count_matches_matches_search_memories_for_a_spoken_question(db):
    """The count agrees with search_memories for a spoken question with stopwords and quotes."""
    add_mems("Annotation guidelines are due on Friday", "My cat is called Biscuit")

    question = 'what did we discuss about "annotation"'

    assert store.count_matches(question) == len(store.search_memories(question, 10))
    assert store.count_matches(question) == 1


def test_fr36_count_matches_respects_window(db):
    """count_matches counts only matches inside the window."""
    add_at("annotation notes from August", "2026-08-20T10:00:00+05:30")
    add_at("annotation notes from September", "2026-09-15T10:00:00+05:30")
    add_at("annotation notes from October", "2026-10-10T10:00:00+05:30")
    add_at("gardening notes from September", "2026-09-16T10:00:00+05:30")

    assert store.count_matches("annotation") == 3
    assert (
        store.count_matches("annotation", since="2026-09-01", until="2026-10-01") == 1
    )
    assert store.count_matches("annotation", since="2026-09-01") == 2
    assert store.count_matches("annotation", until="2026-09-01") == 1


def test_fr36_count_matches_unreadable_bound_is_ignored(db):
    """An unreadable bound is ignored by count_matches, as in search_memories."""
    add_at("annotation notes from August", "2026-08-20T10:00:00+05:30")
    add_at("annotation notes from October", "2026-10-10T10:00:00+05:30")

    assert store.count_matches("annotation", since="last week", until="soon") == 2


@pytest.mark.parametrize(
    "query",
    ['"', "'", "*", "", "what did we about", "AND OR NOT", "quantum chromodynamics"],
)
def test_fr36_count_matches_zero_without_usable_words_or_match(db, query):
    """A query of only stopwords or syntax, or one matching nothing, counts 0."""
    add_mems("The annotation plan is ready")

    assert store.count_matches(query) == 0


def test_fr36_count_matches_zero_on_empty_store(db):
    """count_matches on an empty store is 0."""
    assert store.count_matches("annotation") == 0


def test_fr36_count_functions_and_recent_are_read_only(db):
    """count_memories, recent_memories and count_matches change no row."""
    add_mems("annotation plan", "annotation review")
    before = memory_rows(db)

    store.count_memories()
    store.recent_memories(5)
    store.count_matches("annotation")

    assert memory_rows(db) == before


def memory_texts(path) -> list[str]:
    con = REAL_CONNECT(path)
    try:
        return [r[0] for r in con.execute("SELECT text FROM memories ORDER BY id")]
    finally:
        con.close()


def table_count(path, table: str) -> int:
    con = REAL_CONNECT(path)
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


def test_fr34_forget_one_match_deletes_it_and_keeps_every_other_row(db):
    """With exactly one item containing every query word, that row is gone and every other row remains."""
    add_mems("Gym on Monday", "My cat is called Biscuit", "I study operating systems")
    assert table_count(db, "memories") == 3

    store.forget_memory("gym Monday")

    assert table_count(db, "memories") == 2
    assert sorted(memory_texts(db)) == [
        "I study operating systems",
        "My cat is called Biscuit",
    ]


def test_fr34_forget_returns_the_deleted_row_with_four_fields(db):
    """The result is {"deleted": {id, text, type, created_at}} describing the deleted row."""
    mem = store.add_memory("Gym on Monday", store.PREFERENCE, MEM_TIME)
    add_mems("My cat is called Biscuit")

    result = store.forget_memory("gym Monday")

    assert result == {
        "deleted": {
            "id": mem["id"],
            "text": "Gym on Monday",
            "type": "preference",
            "created_at": MEM_TIME,
        }
    }


def test_fr34_forget_gym_mondays_deletes_stored_gym_on_monday(db):
    """ "gym Mondays" deletes a stored "gym on Monday" (same stemming as find_same)."""
    [mem] = add_mems("gym on Monday")

    result = store.forget_memory("gym Mondays")

    assert result["deleted"]["id"] == mem["id"]
    assert memory_rows(db) == []


def test_fr34_forget_word_the_item_lacks_deletes_nothing(db):
    """ "gym plan" against "gym on Monday" deletes nothing and returns empty candidates."""
    add_mems("gym on Monday")
    before = memory_rows(db)

    result = store.forget_memory("gym plan")

    assert result == {"candidates": []}
    assert memory_rows(db) == before


def test_fr34_forget_two_matches_delete_nothing_and_return_both_in_id_order(db):
    """With two matching items nothing is deleted and both come back as candidates, oldest id first."""
    first, second = add_mems("Gym session on Monday", "Gym session on Friday")
    add_mems("My cat is called Biscuit")
    before = memory_rows(db)

    result = store.forget_memory("gym session")

    assert list(result) == ["candidates"]
    assert result["candidates"] == [
        {
            "id": first["id"],
            "text": "Gym session on Monday",
            "type": "fact",
            "created_at": MEM_TIME,
        },
        {
            "id": second["id"],
            "text": "Gym session on Friday",
            "type": "fact",
            "created_at": MEM_TIME,
        },
    ]
    assert memory_rows(db) == before


def test_fr34_forget_needs_all_words_so_extra_word_narrows_to_one(db):
    """A match needs ALL query words: "gym Friday" matches only the Friday item among two gym items."""
    monday, friday = add_mems("Gym session on Monday", "Gym session on Friday")

    result = store.forget_memory("gym Friday")

    assert result["deleted"]["id"] == friday["id"]
    assert memory_texts(db) == ["Gym session on Monday"]
    assert store.search_memories("monday", 5)[0]["id"] == monday["id"]


def test_fr34_forget_words_split_across_items_match_nothing(db):
    """When each query word is in a different item but no item has both, nothing is deleted."""
    add_mems("Gym on Monday", "Dentist appointment on Friday")
    before = memory_rows(db)

    result = store.forget_memory("gym Friday")

    assert result == {"candidates": []}
    assert memory_rows(db) == before


def test_fr34_forget_no_match_deletes_nothing_and_returns_empty_candidates(db):
    """With no matching item nothing is deleted and the candidates list is empty."""
    add_mems("Gym on Monday", "My cat is called Biscuit")
    before = memory_rows(db)

    result = store.forget_memory("quantum chromodynamics")

    assert result == {"candidates": []}
    assert memory_rows(db) == before


def test_fr34_forget_on_empty_store_returns_empty_candidates(db):
    """With nothing stored, forget deletes nothing and returns empty candidates."""
    assert store.forget_memory("gym Monday") == {"candidates": []}


@pytest.mark.parametrize(
    "query",
    ["", "   ", "the is a", "what did we about", "!!! ???", "'", '"', "*"],
    ids=[
        "empty",
        "blank",
        "only-stopwords",
        "only-stopwords-spoken",
        "only-punctuation",
        "apostrophe",
        "quote",
        "star",
    ],
)
def test_fr34_forget_query_without_content_words_matches_nothing(db, query):
    """A blank, stopword-only or punctuation-only query matches nothing and never deletes everything."""
    add_mems("Gym on Monday", "My cat is called Biscuit")
    before = memory_rows(db)

    result = store.forget_memory(query)

    assert result == {"candidates": []}
    assert memory_rows(db) == before


def test_fr34_forget_removes_the_fts_index_entry_with_the_row(db):
    """The FTS5 index entry goes with the row: the index holds no rowid for the deleted item."""
    gym, cat = add_mems("Gym on Monday", "My cat likes Monday")
    assert index_rowids(db, "gym") == [gym["id"]]
    assert index_rowids(db, "monday") == sorted([gym["id"], cat["id"]])

    store.forget_memory("gym")

    assert index_rowids(db, "gym") == []
    assert index_rowids(db, "monday") == [cat["id"]]


def test_fr34_forget_ambiguous_leaves_the_index_untouched(db):
    """An ambiguous query deletes nothing, so the index still holds both items."""
    first, second = add_mems("Gym session on Monday", "Gym session on Friday")

    store.forget_memory("gym session")

    assert index_rowids(db, "gym") == sorted([first["id"], second["id"]])


def test_fr34_forget_uses_the_same_stems_as_find_same(db):
    """forget matches by the stems find_same uses: a reordered, inflected, stopword-padded query finds the item."""
    [mem] = add_mems("Annotation project deadline is in March")
    text = "the deadline for the annotation project is March"
    assert store.find_same(text)["id"] == mem["id"]

    result = store.forget_memory(text)

    assert result["deleted"]["id"] == mem["id"]
    assert memory_rows(db) == []


def test_fr34_forgotten_item_is_not_returned_by_search_memories(db):
    """After forget, search_memories no longer returns the deleted item."""
    gym, other = add_mems("Gym on Monday", "Gym bag is in the car")
    assert gym["id"] in [m["id"] for m in store.search_memories("gym Monday", 5)]

    store.forget_memory("gym Monday")

    found = [m["id"] for m in store.search_memories("gym Monday", 5)]
    assert gym["id"] not in found
    assert found == [other["id"]]


def test_fr34_forget_leaves_notes_and_reminders_untouched(db):
    """Forgetting a memory deletes nothing from the notes and reminders tables."""
    store.add_note("gym on Monday", MEM_TIME)
    store.add_reminder("gym on Monday", "2026-10-21T09:00:00+05:30", MEM_TIME)
    add_mems("Gym on Monday")

    store.forget_memory("gym Monday")

    assert table_count(db, "notes") == 1
    assert table_count(db, "reminders") == 1
    assert table_count(db, "memories") == 0


def table_rows(path, table: str) -> list[tuple]:
    con = REAL_CONNECT(path)
    try:
        return con.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
    finally:
        con.close()


def test_fr35_wipe_deletes_every_memory_row_and_returns_the_count(db):
    """wipe_memories deletes every memory row and returns how many (8)."""
    add_mems(*[f"separate point number {n}" for n in range(8)])
    assert table_count(db, "memories") == 8

    assert store.wipe_memories() == 8

    assert table_count(db, "memories") == 0
    assert memory_rows(db) == []


def test_fr35_wipe_on_empty_store_returns_zero(db):
    """wipe_memories on an empty store returns 0."""
    assert store.wipe_memories() == 0
    assert memory_rows(db) == []


def test_fr35_wipe_leaves_no_index_entries(db):
    """After a wipe the FTS index itself holds no entry for the deleted items."""
    gym, cat = add_mems("Gym on Monday", "My cat likes Monday")
    assert index_rowids(db, "monday") == sorted([gym["id"], cat["id"]])

    store.wipe_memories()

    assert index_rowids(db, "gym") == []
    assert index_rowids(db, "monday") == []
    assert index_rowids(db, "cat") == []


def test_fr35_wiped_items_are_not_found_by_search(db):
    """After a wipe, search_memories finds nothing."""
    add_mems("Gym on Monday", "My cat likes Monday")

    store.wipe_memories()

    assert store.search_memories("gym Monday", 5) == []
    assert store.count_matches("monday") == 0


def test_fr35_wipe_leaves_notes_reminders_and_concepts_untouched(db):
    """Notes, reminders and concepts rows are identical before and after a wipe."""
    store.add_note("gym on Monday", MEM_TIME)
    store.add_reminder("gym on Monday", "2026-10-21T09:00:00+05:30", MEM_TIME)
    store.log_concept("LoRA", "Low-rank adapters", MEM_TIME)
    add_mems("Gym on Monday", "My cat likes Monday")
    before = {t: table_rows(db, t) for t in ("notes", "reminders", "concepts")}
    assert all(len(rows) == 1 for rows in before.values())

    assert store.wipe_memories() == 2

    after = {t: table_rows(db, t) for t in ("notes", "reminders", "concepts")}
    assert after == before


def test_fr35_memories_added_after_a_wipe_work_normally(db):
    """After a wipe, add_memory, search_memories and find_same work as on a new store."""
    add_mems("Gym on Monday", "My cat likes Monday")
    store.wipe_memories()

    mem = store.add_memory(
        "Annotation project deadline is in March", store.FACT, MEM_TIME
    )

    assert table_count(db, "memories") == 1
    assert [m["id"] for m in store.search_memories("annotation", 5)] == [mem["id"]]
    assert index_rowids(db, "annotation") == [mem["id"]]
    assert store.find_same("Annotation project deadline is in March")["id"] == mem["id"]
    assert store.search_memories("gym", 5) == []


def test_fr35_second_wipe_returns_zero(db):
    """A second wipe right after the first deletes nothing and returns 0."""
    add_mems("Gym on Monday", "My cat likes Monday", "I study operating systems")

    assert store.wipe_memories() == 3
    assert store.wipe_memories() == 0
    assert memory_rows(db) == []


def reminder_columns(path) -> list[str]:
    con = REAL_CONNECT(path)
    try:
        return [r[1] for r in con.execute("PRAGMA table_info(reminders)")]
    finally:
        con.close()


def kind_of(path, row_id: int) -> str:
    con = REAL_CONNECT(path)
    try:
        row = con.execute("SELECT kind FROM reminders WHERE id = ?", (row_id,))
        return row.fetchone()[0]
    finally:
        con.close()


def old_db(monkeypatch, tmp_path):
    """A database made before v3: reminders without a kind column, two rows."""
    path = tmp_path / "old.db"
    con = REAL_CONNECT(path)
    try:
        with con:
            con.execute(
                "CREATE TABLE reminders (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " text TEXT NOT NULL, due_at TEXT NOT NULL,"
                " created_at TEXT NOT NULL, status TEXT NOT NULL)"
            )
            con.execute(
                "INSERT INTO reminders (text, due_at, created_at, status)"
                " VALUES ('old pending', ?, ?, 'pending')",
                (DUE_A, CREATED),
            )
            con.execute(
                "INSERT INTO reminders (text, due_at, created_at, status)"
                " VALUES ('old delivered', ?, ?, 'delivered')",
                (DUE_B, CREATED),
            )
    finally:
        con.close()
    monkeypatch.setattr("server.config.DB_PATH", path)
    return path


def test_fr39_fresh_database_has_kind_column_default_reminder(db):
    """A fresh database's reminders table has a kind column, and add_reminder rows get kind 'reminder'."""
    assert "kind" in reminder_columns(db)

    added = store.add_reminder("call mom", DUE_A, CREATED)

    assert kind_of(db, added["id"]) == "reminder"


def test_fr39_init_adds_kind_to_old_database_and_keeps_rows_as_reminders(
    monkeypatch, tmp_path
):
    """init() on a pre-v3 database adds the kind column and keeps every row, each as a reminder."""
    path = old_db(monkeypatch, tmp_path)
    assert "kind" not in reminder_columns(path)

    store.init()

    assert "kind" in reminder_columns(path)
    assert reminder_rows(path) == [
        (1, "old pending", DUE_A, "pending"),
        (2, "old delivered", DUE_B, "delivered"),
    ]
    assert kind_of(path, 1) == "reminder"
    assert kind_of(path, 2) == "reminder"


def test_fr39_init_twice_on_old_database_does_not_fail(monkeypatch, tmp_path):
    """A second init() after the migration does not fail and changes no row."""
    path = old_db(monkeypatch, tmp_path)
    store.init()
    before = reminder_rows(path)

    store.init()

    assert reminder_rows(path) == before
    assert reminder_columns(path).count("kind") == 1


def test_fr39_old_reminder_still_works_after_migration(monkeypatch, tmp_path):
    """A reminder created before the migration is listed, due, ackable and cancellable afterwards."""
    path = old_db(monkeypatch, tmp_path)
    store.init()
    old = {"id": 1, "text": "old pending", "due_at": DUE_A}

    assert store.list_pending() == [old]
    assert store.list_due(NOW) == [old]
    assert store.get(1)["kind"] == "reminder"
    assert store.ack(1) == old
    assert status_of(path, 1) == store.DELIVERED
    assert store.list_due(NOW) == []

    other = store.add_reminder("new one", DUE_A, CREATED)
    assert store.cancel(other["id"]) == other


def test_fr39_old_pending_reminder_is_cancellable_after_migration(
    monkeypatch, tmp_path
):
    """cancel of a pre-v3 pending reminder returns it and sets it cancelled."""
    path = old_db(monkeypatch, tmp_path)
    store.init()

    assert store.cancel(1) == {"id": 1, "text": "old pending", "due_at": DUE_A}
    assert status_of(path, 1) == store.CANCELLED


def test_fr39_add_notice_stores_pending_notice_due_now_and_returns_dict(db):
    """add_notice stores one pending row of kind notice due at now and returns a dict."""
    notice = store.add_notice("I saved 2 points from our session", NOW)

    assert isinstance(notice, dict)
    assert notice["text"] == "I saved 2 points from our session"
    assert notice["due_at"] == NOW
    rows = reminder_rows(db)
    assert rows == [
        (notice["id"], "I saved 2 points from our session", NOW, store.PENDING)
    ]
    assert kind_of(db, notice["id"]) == "notice"


def test_fr39_list_pending_never_sees_a_notice(db):
    """list_pending (behind list_reminders) leaves out notices."""
    reminder = store.add_reminder("call mom", DUE_A, CREATED)
    store.add_notice("saved 1 point", NOW)

    assert store.list_pending() == [reminder]


def test_fr39_cancel_of_notice_returns_none_and_leaves_it_pending(db):
    """cancel of a notice id returns None and the notice stays pending."""
    notice = store.add_notice("saved 1 point", NOW)

    assert store.cancel(notice["id"]) is None
    assert status_of(db, notice["id"]) == store.PENDING
    assert [r["id"] for r in store.list_due(NOW)] == [notice["id"]]


def test_fr39_list_due_returns_reminders_and_notices_with_three_keys(db):
    """list_due returns due reminders and notices, each with exactly id, text, due_at."""
    reminder = store.add_reminder("call mom", DUE_A, CREATED)
    notice = store.add_notice("saved 1 point", NOW)

    due = store.list_due(NOW)

    assert all(set(r) == {"id", "text", "due_at"} for r in due)
    assert {r["id"] for r in due} == {reminder["id"], notice["id"]}
    assert {r["text"] for r in due} == {"call mom", "saved 1 point"}


def test_fr39_list_due_orders_notices_and_reminders_by_due_at_then_id(db):
    """list_due orders reminders and notices together, oldest due_at first, ties by id."""
    first_tie = store.add_notice("tie notice", DUE_B)
    early = store.add_reminder("early reminder", DUE_A, CREATED)
    second_tie = store.add_reminder("tie reminder", DUE_B, CREATED)
    third_tie = store.add_notice("another tie notice", DUE_B)

    due = store.list_due("2026-10-09T18:00:00+05:30")

    assert [r["id"] for r in due] == [
        early["id"],
        first_tie["id"],
        second_tie["id"],
        third_tie["id"],
    ]


def test_fr39_list_due_excludes_future_notice(db):
    """list_due does not return a notice whose due_at is after now."""
    store.add_notice("future notice", DUE_C)

    assert store.list_due(NOW) == []


def test_fr39_get_tells_the_kind(db):
    """get returns the kind: 'reminder' for a reminder, 'notice' for a notice."""
    reminder = store.add_reminder("call mom", DUE_A, CREATED)
    notice = store.add_notice("saved 1 point", NOW)

    assert store.get(reminder["id"])["kind"] == "reminder"
    assert store.get(notice["id"])["kind"] == "notice"
    assert store.get(notice["id"])["text"] == "saved 1 point"


def test_fr39_ack_of_notice_marks_delivered_and_leaves_list_due(db):
    """ack of a notice makes it delivered and it leaves list_due."""
    notice = store.add_notice("saved 1 point", NOW)
    assert [r["id"] for r in store.list_due(NOW)] == [notice["id"]]

    result = store.ack(notice["id"])

    assert result is not None
    assert result["id"] == notice["id"]
    assert status_of(db, notice["id"]) == store.DELIVERED
    assert store.list_due(NOW) == []


# --- writer guard: judge_point (FR-39, FR-40) ---

T6_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "t6_pairs.json").read_text(encoding="utf-8")
)
T6_PROFILE_TEXT = " ".join(T6_FIXTURE["profile"].values())
T6_PAIRS = {p["id"]: p for p in T6_FIXTURE["pairs"]}
HELD_OUT_PROFILE = (
    "Final-year electronics engineering student in Pune "
    "Work on embedded machine learning"
)
LEAK_USER = (
    "My PCB submission for the sensor board is due on the 28th, so I need to "
    "check the footprint library. The connector ones. I've been building this "
    "sensor board for a climate logger all semester, it's my main project."
)


def t6_params():
    return [
        pytest.param(
            p,
            id=f"pair-{p['id']}-{p['group']}"
            + ("-known-limit" if p["known_limit"] else ""),
        )
        for p in T6_FIXTURE["pairs"]
    ]


def judge_pair(pair_id: int) -> dict:
    pair = T6_PAIRS[pair_id]
    return store.judge_point(
        pair["point"], " ".join(pair["user_turns"]), T6_PROFILE_TEXT
    )


def test_fr39_t6_fixture_has_34_pairs():
    """The frozen T6 fixture holds 34 pairs."""
    assert len(T6_FIXTURE["pairs"]) == 34


@pytest.mark.parametrize("pair", t6_params())
def test_fr39_judge_point_matches_t6_expected_verdict(pair):
    """Each T6 pair gets its expected verdict. Known-limit pairs (D, E, F19, J:
    fabrications that share a word) are expected to PASS the guard (verdict
    None) although wrong by meaning."""
    got = store.judge_point(
        pair["point"], " ".join(pair["user_turns"]), T6_PROFILE_TEXT
    )
    assert got["verdict"] == pair["expected"]


def test_fr39_judge_point_held_out_f_is_ungrounded():
    """A fabricated point sharing no stem with the user's words is ungrounded (held-out f)."""
    got = store.judge_point(
        "Working on a fingerprint-sensor project",
        "How do I read a CSV file in Python? Okay, how do I skip the header row?",
        HELD_OUT_PROFILE,
    )
    assert got["verdict"] == "ungrounded"


def test_fr39_judge_point_held_out_f2_is_ungrounded():
    """A fabricated point sharing no stem with the user's words is ungrounded (held-out f2)."""
    got = store.judge_point(
        "Maintaining a Rust compiler fork",
        "How do I undo my last git commit? Okay, and how do I rename a branch?",
        HELD_OUT_PROFILE,
    )
    assert got["verdict"] == "ungrounded"


def test_fr39_judge_point_held_out_leak_is_known_with_leaked_stems():
    """A point that copies two profile words the user never said is known, leak == final, year."""
    got = store.judge_point(
        "Building a climate logger sensor board as final-year project",
        LEAK_USER,
        HELD_OUT_PROFILE,
    )
    assert got["verdict"] == "known"
    assert got["leak"] == ["final", "year"]


def test_fr39_judge_point_held_out_legitimate_point_passes():
    """The same point without the leaked profile words passes (verdict None)."""
    got = store.judge_point(
        "Building a climate logger sensor board as main project",
        LEAK_USER,
        HELD_OUT_PROFILE,
    )
    assert got["verdict"] is None


def test_fr39_judge_point_returns_scores_and_leak_for_pair_22():
    """Pair 22 scores grounded 0.6, known 0.6 and leak == build, vehicl."""
    got = judge_pair(22)
    assert set(got) == {"verdict", "grounded", "known", "leak"}
    assert got["grounded"] == pytest.approx(0.6)
    assert got["known"] == pytest.approx(0.6)
    assert got["leak"] == ["build", "vehicl"]


def test_fr39_judge_point_empty_profile_never_gives_known():
    """With an empty profile_text the verdict is never known."""
    pair = T6_PAIRS[22]
    got = store.judge_point(pair["point"], " ".join(pair["user_turns"]), "")
    assert got["verdict"] is None
    assert got["known"] == 0
    assert got["leak"] == []


def test_fr39_judge_point_without_content_stems_is_ungrounded():
    """A point with no content stems at all shares zero stems with the user and is ungrounded."""
    got = store.judge_point("the of a", "I study the thermodynamics exam", "")
    assert got["verdict"] == "ungrounded"


def test_fr39_judge_point_assistant_words_never_ground_a_point():
    """Only user turns are passed: a point whose words are not in user_text is ungrounded."""
    got = store.judge_point(
        "Maintaining a Rust compiler fork", "How do I rename a branch?", ""
    )
    assert got["verdict"] == "ungrounded"


def test_fr39_judge_point_known_share_comes_from_config(monkeypatch):
    """Lowering config.WRITER_KNOWN_SHARE to 0.3 makes pair 34 (share 0.33, leak 0) known."""
    assert config.WRITER_KNOWN_SHARE == 0.5
    assert judge_pair(34)["verdict"] is None
    monkeypatch.setattr(config, "WRITER_KNOWN_SHARE", 0.3)
    assert judge_pair(34)["verdict"] == "known"


def test_fr39_judge_point_leak_stems_come_from_config(monkeypatch):
    """Raising config.WRITER_LEAK_STEMS to 3 turns pair 30 (leak 2, share 0.25) from known to None."""
    assert config.WRITER_LEAK_STEMS == 2
    assert judge_pair(30)["verdict"] == "known"
    monkeypatch.setattr(config, "WRITER_LEAK_STEMS", 3)
    assert judge_pair(30)["verdict"] is None


def test_fr39_remember_never_calls_judge_point(db, monkeypatch):
    """store.remember is not guarded: it stores a new row even if judge_point would raise."""

    def boom(*args, **kwargs):
        raise AssertionError("judge_point must not be called by remember")

    monkeypatch.setattr(store, "judge_point", boom)

    item = store.remember(
        "fingerprint sensor project", "project", "2026-10-26T10:00:00+05:30"
    )

    assert item["new"] is True
    assert len(memory_rows(db)) == 1
