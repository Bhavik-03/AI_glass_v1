import sqlite3

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
    """get returns {id, text, due_at} for an existing reminder."""
    added = store.add_reminder("call mom", DUE_A, CREATED)

    assert store.get(added["id"]) == added


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
