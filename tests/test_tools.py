"""Tool declarations and dispatch tests (FR-5, FR-7). search.search is faked: no network."""

import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from server import config, search, session, store, tools

NOW = datetime(2026, 10, 10, 9, 0, tzinfo=ZoneInfo(config.TIMEZONE))
FIXED_ISO = "2026-10-09T14:00:00+05:30"


def fake_search(monkeypatch, result=None, error=None):
    calls = []

    def fake(query):
        calls.append(query)
        if error:
            raise error
        return result

    monkeypatch.setattr(search, "search", fake)
    return calls


def test_fr5_declares_web_search_with_required_query():
    """DECLARATIONS has one web_search entry whose schema requires a string 'query'."""
    decls = [d for d in tools.DECLARATIONS if d["name"] == "web_search"]
    assert len(decls) == 1
    decl = decls[0]
    assert decl["description"]
    schema = decl["parameters_json_schema"]
    assert schema["type"] == "object"
    assert schema["properties"]["query"]["type"] == "string"
    assert "query" in schema["required"]


def test_fr5_web_search_returns_results_from_search(monkeypatch):
    """run('web_search') returns {results: [...]} from search and passes the query unchanged."""
    results = [{"title": "T", "url": "https://x.test", "content": "C"}]
    calls = fake_search(monkeypatch, result=results)

    out = tools.run("web_search", {"query": "weather in Pune"}, NOW)

    assert out == {"results": results}
    assert calls == ["weather in Pune"]


def test_fr7_search_failure_returns_error_not_crash(monkeypatch):
    """When search raises, run returns only a non-empty {error} string instead of raising."""
    fake_search(monkeypatch, error=RuntimeError("boom"))

    out = tools.run("web_search", {"query": "news"}, NOW)

    assert list(out) == ["error"]
    assert isinstance(out["error"], str) and out["error"]


def test_fr7_unknown_tool_returns_error(monkeypatch):
    """An unknown tool name returns {error} mentioning the name and runs no search."""
    calls = fake_search(monkeypatch, result=[])

    out = tools.run("launch_rocket", {"query": "x"}, NOW)

    assert list(out) == ["error"]
    assert "launch_rocket" in out["error"]
    assert calls == []


@pytest.mark.parametrize(
    "args",
    [{}, {"query": 5}, {"query": "  "}, {"query": ""}, None],
    ids=["missing", "non-string", "whitespace", "empty", "not-a-dict"],
)
def test_fr7_bad_arguments_return_error(monkeypatch, args):
    """Bad web_search arguments return {error} and runs no search."""
    calls = fake_search(monkeypatch, result=[])

    out = tools.run("web_search", args, NOW)

    assert list(out) == ["error"]
    assert isinstance(out["error"], str) and out["error"]
    assert calls == []


def declaration(name):
    matches = [d for d in tools.DECLARATIONS if d["name"] == name]
    assert len(matches) == 1
    return matches[0]


def test_fr5_web_search_declaration_forbids_private_content():
    """The web_search declaration says the query must never contain note, reminder, concept or screen content."""
    description = declaration("web_search")["description"].lower()
    assert "never" in description
    for word in ("note", "reminder", "concept", "screen"):
        assert word in description


def test_fr8_declares_add_note_with_required_text():
    """DECLARATIONS has one add_note entry whose schema requires a string 'text'."""
    decl = declaration("add_note")
    assert decl["description"]
    schema = decl["parameters_json_schema"]
    assert schema["type"] == "object"
    assert schema["properties"]["text"]["type"] == "string"
    assert "text" in schema["required"]


def test_fr10_declares_list_notes_without_required_parameters():
    """DECLARATIONS has one list_notes entry that requires no parameters."""
    decl = declaration("list_notes")
    assert decl["description"]
    schema = decl["parameters_json_schema"]
    assert schema["type"] == "object"
    assert not schema.get("required")


def test_fr8_add_note_returns_id_text_created_at_and_stores_one_row(db, fixed_now):
    """run('add_note') returns exactly {id, text, created_at} and stores one note."""
    out = tools.run("add_note", {"text": "buy milk"}, fixed_now)

    assert set(out) == {"id", "text", "created_at"}
    assert out["text"] == "buy milk"
    assert out["created_at"] == FIXED_ISO
    rows = store.list_notes()
    assert len(rows) == 1
    assert rows[0]["text"] == "buy milk"
    assert rows[0]["created_at"] == FIXED_ISO


def test_fr8_add_note_stores_text_as_given(db, fixed_now):
    """The note text is stored unchanged, not stripped."""
    out = tools.run("add_note", {"text": "  call mom  "}, fixed_now)

    assert out["text"] == "  call mom  "
    assert store.list_notes()[0]["text"] == "  call mom  "


@pytest.mark.parametrize(
    "args",
    [{}, {"text": 5}, {"text": None}, {"text": ""}, {"text": "   "}],
    ids=["missing", "non-string", "none", "empty", "whitespace"],
)
def test_fr8_add_note_bad_text_returns_error_and_stores_nothing(db, fixed_now, args):
    """Missing, non-string, empty or blank text returns {error} and stores nothing."""
    out = tools.run("add_note", args, fixed_now)

    assert "text" in out["error"]
    assert store.list_notes() == []


def test_fr10_list_notes_empty_returns_empty_list(db, fixed_now):
    """run('list_notes') on an empty database returns {notes: []}."""
    assert tools.run("list_notes", {}, fixed_now) == {"notes": []}


def test_fr10_list_notes_returns_all_newest_first(db):
    """run('list_notes') returns every note as {id, text, created_at}, newest first."""
    first = tools.run("add_note", {"text": "first"}, NOW.replace(hour=8))
    second = tools.run("add_note", {"text": "second"}, NOW.replace(hour=9))

    out = tools.run("list_notes", {}, NOW.replace(hour=10))

    assert list(out) == ["notes"]
    assert out["notes"] == [second, first]
    assert [n["text"] for n in out["notes"]] == ["second", "first"]
    assert out["notes"][0]["created_at"] == "2026-10-10T09:00:00+05:30"
    assert out["notes"][1]["created_at"] == "2026-10-10T08:00:00+05:30"


def test_fr10_list_notes_ignores_extra_arguments(db, fixed_now):
    """list_notes takes no arguments: extra ones are ignored."""
    added = tools.run("add_note", {"text": "x"}, fixed_now)

    out = tools.run("list_notes", {"junk": 1}, fixed_now)

    assert out == {"notes": [added]}


def test_fr10_stored_values_come_back_in_add_note_result(db, fixed_now):
    """add_note's result equals what list_notes returns, so Gemini can repeat it."""
    added = tools.run("add_note", {"text": "water the plants"}, fixed_now)

    listed = tools.run("list_notes", {}, fixed_now)

    assert listed["notes"] == [added]


def test_fr9_declares_add_reminder_with_required_text_and_due_at():
    """DECLARATIONS has one add_reminder entry whose schema requires string 'text' and 'due_at'."""
    decl = declaration("add_reminder")
    assert decl["description"]
    schema = decl["parameters_json_schema"]
    assert schema["type"] == "object"
    assert schema["properties"]["text"]["type"] == "string"
    assert schema["properties"]["due_at"]["type"] == "string"
    assert "text" in schema["required"]
    assert "due_at" in schema["required"]


def test_fr9_add_reminder_returns_id_text_due_at_and_stores_one_row(db, fixed_now):
    """run('add_reminder') returns exactly {id, text, due_at, due_spoken} and stores one pending reminder."""
    out = tools.run(
        "add_reminder",
        {"text": "call the lab", "due_at": "2026-10-10T17:00:00+05:30"},
        fixed_now,
    )

    assert set(out) == {"id", "text", "due_at", "due_spoken"}
    assert out["text"] == "call the lab"
    assert out["due_at"] == "2026-10-10T17:00:00+05:30"
    assert out["due_spoken"] == "10 October, 5 pm"
    rows = store.list_pending()
    assert len(rows) == 1
    assert rows[0]["id"] == out["id"]
    assert rows[0]["text"] == "call the lab"
    assert rows[0]["due_at"] == "2026-10-10T17:00:00+05:30"


def test_fr9_add_reminder_converts_due_at_to_configured_time_zone(db, fixed_now):
    """A due_at given in another offset (Z) is converted to +05:30 in the result and the row."""
    out = tools.run(
        "add_reminder",
        {"text": "take pill", "due_at": "2026-10-09T17:00:00Z"},
        fixed_now,
    )

    assert out["due_at"] == "2026-10-09T22:30:00+05:30"
    assert store.list_pending()[0]["due_at"] == "2026-10-09T22:30:00+05:30"


def test_fr9_add_reminder_drops_fractional_seconds(db, fixed_now):
    """The stored due_at has seconds precision: fractional seconds are dropped."""
    out = tools.run(
        "add_reminder",
        {"text": "stand up", "due_at": "2026-10-09T16:00:00.789+05:30"},
        fixed_now,
    )

    assert out["due_at"] == "2026-10-09T16:00:00+05:30"
    assert store.list_pending()[0]["due_at"] == "2026-10-09T16:00:00+05:30"


def test_fr9_add_reminder_due_at_equal_to_now_is_accepted(db, fixed_now):
    """A due_at equal to now is not in the past and is stored."""
    out = tools.run(
        "add_reminder", {"text": "right now", "due_at": FIXED_ISO}, fixed_now
    )

    assert set(out) == {"id", "text", "due_at", "due_spoken"}
    assert out["due_at"] == FIXED_ISO
    assert out["due_spoken"] == "2 pm"
    assert len(store.list_pending()) == 1


def test_fr9_add_reminder_stores_text_as_given(db, fixed_now):
    """The reminder text is stored unchanged, not stripped."""
    out = tools.run(
        "add_reminder",
        {"text": "  call mom  ", "due_at": "2026-10-10T09:00:00+05:30"},
        fixed_now,
    )

    assert out["text"] == "  call mom  "
    assert store.list_pending()[0]["text"] == "  call mom  "


@pytest.mark.parametrize(
    "args",
    [
        {"due_at": "2026-10-10T17:00:00+05:30"},
        {"text": 5, "due_at": "2026-10-10T17:00:00+05:30"},
        {"text": None, "due_at": "2026-10-10T17:00:00+05:30"},
        {"text": "", "due_at": "2026-10-10T17:00:00+05:30"},
        {"text": "   ", "due_at": "2026-10-10T17:00:00+05:30"},
    ],
    ids=["missing", "non-string", "none", "empty", "whitespace"],
)
def test_fr9_add_reminder_bad_text_returns_error_and_stores_nothing(
    db, fixed_now, args
):
    """Missing, non-string, empty or blank text returns {error} naming 'text' and stores nothing."""
    out = tools.run("add_reminder", args, fixed_now)

    assert "text" in out["error"]
    assert store.list_pending() == []


@pytest.mark.parametrize(
    "due_at",
    [
        None,
        5,
        "",
        "tomorrow at 5",
        "2026-13-45T10:00:00+05:30",
        "2026-10-10T17:00:00",
        "2026-10-10",
    ],
    ids=[
        "none",
        "non-string",
        "empty",
        "not-iso",
        "invalid-date",
        "naive",
        "date-only",
    ],
)
def test_fr9_add_reminder_bad_due_at_returns_error_and_stores_nothing(
    db, fixed_now, due_at
):
    """A missing, non-string, non-ISO 8601 or offset-less due_at returns {error} naming 'due_at'."""
    out = tools.run("add_reminder", {"text": "x", "due_at": due_at}, fixed_now)

    assert "due_at" in out["error"]
    assert store.list_pending() == []


def test_fr9_add_reminder_missing_due_at_returns_error_and_stores_nothing(
    db, fixed_now
):
    """An absent due_at argument returns {error} naming 'due_at' and stores nothing."""
    out = tools.run("add_reminder", {"text": "x"}, fixed_now)

    assert "due_at" in out["error"]
    assert store.list_pending() == []


@pytest.mark.parametrize(
    "due_at",
    ["2026-10-09T13:59:00+05:30", "2026-10-09T08:00:00Z"],
    ids=["one-minute-ago", "past-given-in-utc"],
)
def test_fr9_add_reminder_past_due_at_returns_error_and_stores_nothing(
    db, fixed_now, due_at
):
    """A due_at before now (in any offset) returns {error} containing 'past' and stores nothing."""
    out = tools.run("add_reminder", {"text": "x", "due_at": due_at}, fixed_now)

    assert "past" in out["error"]
    assert store.list_pending() == []


def test_fr10_add_reminder_result_matches_stored_values(db, fixed_now):
    """add_reminder's result equals the stored reminder, so Gemini can repeat it back."""
    added = tools.run(
        "add_reminder",
        {"text": "call the lab", "due_at": "2026-10-10T11:30:00Z"},
        fixed_now,
    )

    rows = store.list_pending()

    assert len(rows) == 1
    assert added == {
        "id": rows[0]["id"],
        "text": rows[0]["text"],
        "due_at": rows[0]["due_at"],
        "due_spoken": "10 October, 5 pm",
    }


DUE_A = "2026-10-10T10:00:00+05:30"
DUE_B = "2026-10-10T12:00:00+05:30"
DUE_C = "2026-10-10T15:00:00+05:30"


def add_pending(text, due_at):
    return store.add_reminder(text, due_at, FIXED_ISO)


def status_in_db(db_path, reminder_id):
    con = sqlite3.connect(db_path)
    try:
        row = con.execute(
            "SELECT status FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
    finally:
        con.close()
    return row[0]


def test_fr9_declares_list_reminders_without_required_parameters():
    """DECLARATIONS has one list_reminders entry that requires no parameters."""
    decl = declaration("list_reminders")
    assert decl["description"]
    schema = decl["parameters_json_schema"]
    assert schema["type"] == "object"
    assert not schema.get("required")


def test_fr9_declares_cancel_reminder_with_required_integer_id():
    """DECLARATIONS has one cancel_reminder entry whose schema requires an integer 'id'."""
    decl = declaration("cancel_reminder")
    assert decl["description"]
    schema = decl["parameters_json_schema"]
    assert schema["type"] == "object"
    assert schema["properties"]["id"]["type"] == "integer"
    assert "id" in schema["required"]


def test_fr9_list_reminders_empty_returns_empty_list(db, fixed_now):
    """run('list_reminders') with no pending reminders returns {reminders: []}."""
    assert tools.run("list_reminders", {}, fixed_now) == {"reminders": []}


def test_fr9_list_reminders_returns_pending_ordered_by_due_at(db, fixed_now):
    """list_reminders returns pending reminders as {id, text, due_at, due_spoken}, ordered by due_at."""
    late = add_pending("late", DUE_C)
    early = add_pending("early", DUE_A)
    middle = add_pending("middle", DUE_B)

    out = tools.run("list_reminders", {}, fixed_now)

    assert list(out) == ["reminders"]
    assert [r["id"] for r in out["reminders"]] == [
        early["id"],
        middle["id"],
        late["id"],
    ]
    for r in out["reminders"]:
        assert set(r) == {"id", "text", "due_at", "due_spoken"}
    assert [r["text"] for r in out["reminders"]] == ["early", "middle", "late"]
    assert [r["due_at"] for r in out["reminders"]] == [DUE_A, DUE_B, DUE_C]
    assert [r["due_spoken"] for r in out["reminders"]] == [
        "10 October, 10 am",
        "10 October, 12 pm",
        "10 October, 3 pm",
    ]


def test_fr9_list_reminders_excludes_cancelled_and_delivered(db, fixed_now):
    """list_reminders never lists cancelled or delivered reminders."""
    keep = add_pending("keep", DUE_C)
    cancelled = add_pending("cancelled", DUE_A)
    delivered = add_pending("delivered", DUE_B)
    store.cancel(cancelled["id"])
    store.ack(delivered["id"])

    out = tools.run("list_reminders", {}, fixed_now)

    assert [r["id"] for r in out["reminders"]] == [keep["id"]]


def test_fr9_list_reminders_ignores_extra_arguments(db, fixed_now):
    """list_reminders takes no arguments: extra ones are ignored."""
    added = add_pending("x", DUE_A)

    out = tools.run("list_reminders", {"junk": 1}, fixed_now)

    assert [r["id"] for r in out["reminders"]] == [added["id"]]


def test_fr9_cancel_reminder_returns_stored_values_and_cancels(db, fixed_now):
    """cancel_reminder returns exactly {id, text, due_at, status: cancelled} and cancels the row."""
    added = add_pending("call the lab", DUE_A)

    out = tools.run("cancel_reminder", {"id": added["id"]}, fixed_now)

    assert set(out) == {"id", "text", "due_at", "status"}
    assert out["id"] == added["id"]
    assert out["text"] == "call the lab"
    assert out["due_at"] == DUE_A
    assert out["status"] == store.CANCELLED
    assert status_in_db(db, added["id"]) == store.CANCELLED
    assert store.list_pending() == []


def test_fr9_cancel_reminder_accepts_integral_float_id(db, fixed_now):
    """cancel_reminder accepts an integral float id such as 3.0 and treats it as the int."""
    added = add_pending("call the lab", DUE_A)

    out = tools.run("cancel_reminder", {"id": float(added["id"])}, fixed_now)

    assert out["id"] == added["id"]
    assert out["status"] == store.CANCELLED
    assert status_in_db(db, added["id"]) == store.CANCELLED


@pytest.mark.parametrize(
    "args",
    [
        {"id": True},
        {"id": False},
        {"id": "abc"},
        {"id": "3"},
        {"id": None},
        {"id": 3.5},
        {"id": [1]},
        {"id": 10**30},
        {"id": -(10**30)},
        {"id": 1e30},
        {},
    ],
    ids=[
        "true",
        "false",
        "abc",
        "numeric-string",
        "none",
        "fraction",
        "list",
        "huge-int",
        "huge-negative-int",
        "huge-float",
        "missing",
    ],
)
def test_fr9_cancel_reminder_bad_id_returns_error_and_cancels_nothing(
    db, fixed_now, args
):
    """A missing, bool, string, None, fractional, list or out-of-range id returns {error} naming 'id'."""
    added = add_pending("keep", DUE_A)

    out = tools.run("cancel_reminder", args, fixed_now)

    assert "id" in out["error"]
    assert [r["id"] for r in store.list_pending()] == [added["id"]]
    assert status_in_db(db, added["id"]) == store.PENDING


def test_fr9_cancel_reminder_unknown_id_returns_error(db, fixed_now):
    """An unknown id returns {error} containing 'no pending reminder' and changes nothing."""
    added = add_pending("keep", DUE_A)

    out = tools.run("cancel_reminder", {"id": 999}, fixed_now)

    assert "no pending reminder" in out["error"]
    assert [r["id"] for r in store.list_pending()] == [added["id"]]


def test_fr9_cancel_reminder_already_cancelled_returns_error(db, fixed_now):
    """Cancelling twice: the second call returns 'no pending reminder' and the row stays cancelled."""
    added = add_pending("call the lab", DUE_A)
    tools.run("cancel_reminder", {"id": added["id"]}, fixed_now)

    out = tools.run("cancel_reminder", {"id": added["id"]}, fixed_now)

    assert "no pending reminder" in out["error"]
    assert status_in_db(db, added["id"]) == store.CANCELLED


def test_fr9_cancel_reminder_delivered_returns_error_and_stays_delivered(db, fixed_now):
    """A delivered reminder returns 'no pending reminder' and is not changed to cancelled."""
    added = add_pending("call the lab", DUE_A)
    store.ack(added["id"])

    out = tools.run("cancel_reminder", {"id": added["id"]}, fixed_now)

    assert "no pending reminder" in out["error"]
    assert status_in_db(db, added["id"]) == store.DELIVERED
    assert tools.run("list_reminders", {}, fixed_now) == {"reminders": []}


def test_fr9_cancelled_reminder_disappears_from_list_reminders(db, fixed_now):
    """After a successful cancel, list_reminders no longer returns that reminder."""
    gone = add_pending("gone", DUE_A)
    keep = add_pending("keep", DUE_B)

    tools.run("cancel_reminder", {"id": gone["id"]}, fixed_now)

    out = tools.run("list_reminders", {}, fixed_now)
    assert [r["id"] for r in out["reminders"]] == [keep["id"]]


def test_fr10_cancel_by_description_flow_returns_stored_values(db, fixed_now):
    """list_reminders then cancel_reminder with the listed id cancels it and returns the stored values."""
    add_pending("water plants", DUE_A)
    lab = add_pending("call the lab", DUE_B)

    listed = tools.run("list_reminders", {}, fixed_now)["reminders"]
    match = next(r for r in listed if "lab" in r["text"])
    out = tools.run("cancel_reminder", {"id": match["id"]}, fixed_now)

    assert out == {
        "id": lab["id"],
        "text": "call the lab",
        "due_at": DUE_B,
        "status": store.CANCELLED,
    }


IST = ZoneInfo("Asia/Kolkata")
DUE_5PM = datetime(2026, 10, 9, 17, 0, tzinfo=IST)


def reminder(due_at, text="call the lab"):
    return {"id": 1, "text": text, "due_at": due_at}


def spoken_at_age(age_s, due=DUE_5PM, text="call the lab"):
    return tools.reminder_text(
        reminder(due.isoformat(), text), due + timedelta(seconds=age_s)
    )


def test_fr13_missed_after_is_60_seconds():
    """config.MISSED_AFTER_S is 60."""
    assert config.MISSED_AFTER_S == 60


@pytest.mark.parametrize(
    ("age_s", "prefix"),
    [
        (0, "Reminder"),
        (59, "Reminder"),
        (60, "Missed reminder"),
        (61, "Missed reminder"),
        (3 * 3600, "Missed reminder"),
    ],
    ids=["0s", "59s", "60s", "61s", "3h"],
)
def test_fr13_prefix_depends_on_age_against_missed_after(age_s, prefix):
    """Due less than 60 s ago reads 'Reminder'; 60 s or more ago reads 'Missed reminder'."""
    assert spoken_at_age(age_s) == f"{prefix}, 5 pm: call the lab"


def test_fr13_spec_example_reminder():
    """A reminder due now reads exactly 'Reminder, 5 pm: call the lab'."""
    assert spoken_at_age(5) == "Reminder, 5 pm: call the lab"


def test_fr13_spec_example_missed_with_date():
    """A reminder missed on an earlier date reads 'Missed reminder, 8 October, 5 pm: call the lab'."""
    due = datetime(2026, 10, 8, 17, 0, tzinfo=IST)
    now = datetime(2026, 10, 9, 9, 0, tzinfo=IST)

    out = tools.reminder_text(reminder(due.isoformat()), now)

    assert out == "Missed reminder, 8 October, 5 pm: call the lab"


def test_fr13_future_reminder_reads_as_plain_reminder():
    """A reminder due after now (negative age) is spoken as a plain 'Reminder'."""
    now = datetime(2026, 10, 9, 16, 0, tzinfo=IST)

    out = tools.reminder_text(reminder(DUE_5PM.isoformat()), now)

    assert out == "Reminder, 5 pm: call the lab"


@pytest.mark.parametrize(
    ("hour", "minute", "spoken"),
    [
        (0, 0, "12 am"),
        (12, 0, "12 pm"),
        (0, 30, "12:30 am"),
        (12, 30, "12:30 pm"),
        (0, 5, "12:05 am"),
        (1, 0, "1 am"),
        (11, 59, "11:59 am"),
        (23, 59, "11:59 pm"),
        (17, 0, "5 pm"),
        (17, 30, "5:30 pm"),
        (9, 5, "9:05 am"),
    ],
)
def test_fr13_time_uses_12_hour_clock_with_minutes_only_when_nonzero(
    hour, minute, spoken
):
    """12-hour clock, lowercase am/pm, no leading zero on the hour, ':MM' only when non-zero."""
    due = datetime(2026, 10, 9, hour, minute, tzinfo=IST)

    out = spoken_at_age(0, due=due)

    assert out == f"Reminder, {spoken}: call the lab"


def test_fr13_five_pm_has_no_colon_zero_zero():
    """5 pm reads '5 pm' and never '5:00 pm'."""
    assert ":00" not in spoken_at_age(0)


def test_fr13_same_day_has_no_date():
    """A due date equal to today's date (in the configured zone) adds no date."""
    out = spoken_at_age(3 * 3600)

    assert out == "Missed reminder, 5 pm: call the lab"


def test_fr13_yesterday_adds_date_without_leading_zero():
    """A due date that is not today adds 'D Month' (no leading zero) before the time."""
    due = datetime(2026, 10, 8, 17, 0, tzinfo=IST)
    now = datetime(2026, 10, 9, 9, 0, tzinfo=IST)

    assert (
        tools.reminder_text(reminder(due.isoformat()), now)
        == "Missed reminder, 8 October, 5 pm: call the lab"
    )


def test_fr13_date_uses_day_number_and_full_month_name():
    """The date is the day number without a leading zero and the full month name."""
    due = datetime(2026, 3, 5, 9, 30, tzinfo=IST)
    now = datetime(2026, 3, 6, 9, 0, tzinfo=IST)

    out = tools.reminder_text(reminder(due.isoformat()), now)

    assert out == "Missed reminder, 5 March, 9:30 am: call the lab"


def test_fr13_tomorrow_dated_future_reminder_adds_date():
    """A future reminder on another date reads 'Reminder, 10 October, 5 pm: ...'."""
    due = datetime(2026, 10, 10, 17, 0, tzinfo=IST)
    now = datetime(2026, 10, 9, 20, 0, tzinfo=IST)

    out = tools.reminder_text(reminder(due.isoformat()), now)

    assert out == "Reminder, 10 October, 5 pm: call the lab"


def test_fr13_due_at_in_utc_is_converted_to_configured_zone():
    """due_at '2026-10-08T20:00:00Z' is 9 Oct 01:30 IST: today in IST, so no date and '1:30 am'."""
    now = datetime(2026, 10, 9, 1, 30, tzinfo=IST)

    out = tools.reminder_text(reminder("2026-10-08T20:00:00Z"), now)

    assert out == "Reminder, 1:30 am: call the lab"


def test_fr13_now_in_utc_is_converted_to_configured_zone():
    """now 2026-10-09T20:00 UTC is 10 Oct 01:30 IST, so a 10 Oct 02:00 IST reminder is today: no date."""
    now = datetime(2026, 10, 9, 20, 0, tzinfo=UTC)

    out = tools.reminder_text(reminder("2026-10-10T02:00:00+05:30"), now)

    assert out == "Reminder, 2 am: call the lab"


def test_fr13_age_is_computed_across_different_offsets():
    """Age compares instants: due 17:00 IST vs now 11:31 UTC (17:01 IST) is 60 s, so missed."""
    now = datetime(2026, 10, 9, 11, 31, tzinfo=UTC)

    out = tools.reminder_text(reminder(DUE_5PM.isoformat()), now)

    assert out == "Missed reminder, 5 pm: call the lab"


@pytest.mark.parametrize(
    "text",
    [
        "call the lab",
        "Call Dr. Rao, then email: report!",
        "  spaced  ",
        "pay 5:30 bill?",
    ],
)
def test_fr13_reminder_text_is_spoken_unchanged(text):
    """The reminder's text follows the colon unchanged, punctuation and spacing included."""
    assert spoken_at_age(0, text=text) == f"Reminder, 5 pm: {text}"


# --- due_spoken: speakable time string shared with reminder_text (FR-9, FR-10). ---

MIDNIGHT = datetime(2026, 10, 9, 0, 0, tzinfo=IST)


@pytest.mark.parametrize(
    ("due", "now", "spoken"),
    [
        (datetime(2026, 10, 10, 17, 0, tzinfo=IST), NOW, "5 pm"),
        (datetime(2026, 10, 9, 17, 0, tzinfo=IST), NOW, "9 October, 5 pm"),
        (datetime(2026, 10, 10, 17, 0, tzinfo=IST), MIDNIGHT, "10 October, 5 pm"),
        (datetime(2026, 10, 9, 17, 30, tzinfo=IST), MIDNIGHT, "5:30 pm"),
        (datetime(2026, 10, 9, 0, 47, tzinfo=IST), MIDNIGHT, "12:47 am"),
        (datetime(2026, 10, 9, 0, 0, tzinfo=IST), MIDNIGHT, "12 am"),
        (datetime(2026, 10, 9, 12, 0, tzinfo=IST), MIDNIGHT, "12 pm"),
        (datetime(2026, 10, 9, 12, 5, tzinfo=IST), MIDNIGHT, "12:05 pm"),
        (datetime(2026, 10, 9, 23, 59, tzinfo=IST), MIDNIGHT, "11:59 pm"),
        (datetime(2026, 10, 9, 9, 5, tzinfo=IST), MIDNIGHT, "9:05 am"),
        (datetime(2026, 3, 5, 9, 30, tzinfo=IST), MIDNIGHT, "5 March, 9:30 am"),
        (datetime(2026, 10, 8, 17, 0, tzinfo=IST), MIDNIGHT, "8 October, 5 pm"),
        (datetime(2026, 10, 9, 17, 0, 42, tzinfo=IST), MIDNIGHT, "5 pm"),
    ],
    ids=[
        "today-5pm",
        "yesterday-vs-now-10th",
        "other-day-5pm",
        "today-5-30pm",
        "today-12-47am",
        "midnight",
        "noon",
        "12-05pm",
        "11-59pm",
        "9-05am",
        "other-month-no-leading-zero",
        "yesterday",
        "seconds-ignored",
    ],
)
def test_fr10_spoken_when_formats_time_and_adds_date_only_when_not_today(
    due, now, spoken
):
    """spoken_when gives '5 pm' / '5:30 pm' / '12:47 am' today and '<day> <Month>, <time>' on another day."""
    assert tools.spoken_when(due, now) == spoken


def test_fr10_spoken_when_due_in_utc_is_converted_to_configured_zone():
    """A due in UTC is converted to Asia/Kolkata first: 2026-10-09T19:00Z is 10 Oct 00:30 IST."""
    now = datetime(2026, 10, 10, 0, 30, tzinfo=IST)
    due = datetime(2026, 10, 9, 19, 0, tzinfo=UTC)

    assert tools.spoken_when(due, now) == "12:30 am"


def test_fr10_spoken_when_due_utc_date_differs_from_kolkata_date():
    """2026-10-09T19:00Z is 10 Oct in Kolkata: with now on 9 Oct (Kolkata) the date is added."""
    now = datetime(2026, 10, 9, 14, 0, tzinfo=IST)
    due = datetime(2026, 10, 9, 19, 0, tzinfo=UTC)

    assert tools.spoken_when(due, now) == "10 October, 12:30 am"


def test_fr10_spoken_when_now_in_utc_is_converted_to_configured_zone():
    """now 2026-10-09T20:00 UTC is 10 Oct 01:30 IST, so a 10 Oct 02:00 IST due is today: no date."""
    now = datetime(2026, 10, 9, 20, 0, tzinfo=UTC)
    due = datetime(2026, 10, 10, 2, 0, tzinfo=IST)

    assert tools.spoken_when(due, now) == "2 am"


@pytest.mark.parametrize(
    ("hour", "minute", "spoken"),
    [(14, 0, "2 pm"), (17, 0, "5 pm"), (17, 30, "5:30 pm"), (23, 59, "11:59 pm")],
)
def test_fr10_add_reminder_due_spoken_today(db, fixed_now, hour, minute, spoken):
    """A reminder due later today has a due_spoken without a date, e.g. '5 pm', '5:30 pm'."""
    due_at = datetime(2026, 10, 9, hour, minute, tzinfo=IST).isoformat()

    out = tools.run("add_reminder", {"text": "x", "due_at": due_at}, fixed_now)

    assert out["due_spoken"] == spoken


@pytest.mark.parametrize(
    ("hour", "minute", "spoken"),
    [(0, 0, "12 am"), (0, 47, "12:47 am"), (12, 0, "12 pm"), (12, 30, "12:30 pm")],
)
def test_fr10_add_reminder_due_spoken_midnight_and_noon(db, hour, minute, spoken):
    """12 am / 12 pm use the 12-hour clock: '12 am', '12:47 am', '12 pm', '12:30 pm'."""
    due_at = datetime(2026, 10, 9, hour, minute, tzinfo=IST).isoformat()

    out = tools.run("add_reminder", {"text": "x", "due_at": due_at}, MIDNIGHT)

    assert out["due_spoken"] == spoken


def test_fr10_add_reminder_due_spoken_other_day_has_date(db, fixed_now):
    """A reminder due on another day has '<day> <Month>, <time>' as due_spoken."""
    out = tools.run(
        "add_reminder",
        {"text": "call the lab", "due_at": "2026-10-10T17:00:00+05:30"},
        fixed_now,
    )

    assert out["due_spoken"] == "10 October, 5 pm"


def test_fr10_add_reminder_due_spoken_utc_is_converted_to_kolkata(db, fixed_now):
    """A due_at given as UTC is converted to Kolkata before formatting: 11:30Z is 5 pm IST."""
    out = tools.run(
        "add_reminder",
        {"text": "x", "due_at": "2026-10-09T11:30:00Z"},
        fixed_now,
    )

    assert out["due_at"] == "2026-10-09T17:00:00+05:30"
    assert out["due_spoken"] == "5 pm"


def test_fr10_add_reminder_due_spoken_utc_date_is_kolkata_date(db, fixed_now):
    """A UTC due_at on 9 Oct that is 10 Oct in Kolkata gets the Kolkata date in due_spoken."""
    out = tools.run(
        "add_reminder",
        {"text": "x", "due_at": "2026-10-09T19:00:00Z"},
        fixed_now,
    )

    assert out["due_at"] == "2026-10-10T00:30:00+05:30"
    assert out["due_spoken"] == "10 October, 12:30 am"


def test_fr10_add_reminder_due_spoken_uses_seconds_precision_stored_value(
    db, fixed_now
):
    """due_spoken is built from the stored (seconds precision) due_at: fractions are ignored."""
    out = tools.run(
        "add_reminder",
        {"text": "x", "due_at": "2026-10-09T16:00:00.789+05:30"},
        fixed_now,
    )

    assert out["due_spoken"] == "4 pm"


def test_fr10_add_reminder_error_has_no_due_spoken(db, fixed_now):
    """An add_reminder error is only {error}: no due_spoken."""
    out = tools.run(
        "add_reminder", {"text": "x", "due_at": "2026-10-09T13:00:00+05:30"}, fixed_now
    )

    assert list(out) == ["error"]


def test_fr10_list_reminders_items_carry_due_spoken_today_and_other_day(db, fixed_now):
    """Each list_reminders item has the right due_spoken: no date for today, a date for another day."""
    today = add_pending("water plants", "2026-10-09T17:30:00+05:30")
    tomorrow = add_pending("call the lab", "2026-10-10T17:00:00+05:30")

    out = tools.run("list_reminders", {}, fixed_now)

    assert out == {
        "reminders": [
            {
                "id": today["id"],
                "text": "water plants",
                "due_at": "2026-10-09T17:30:00+05:30",
                "due_spoken": "5:30 pm",
            },
            {
                "id": tomorrow["id"],
                "text": "call the lab",
                "due_at": "2026-10-10T17:00:00+05:30",
                "due_spoken": "10 October, 5 pm",
            },
        ]
    }


def test_fr10_list_reminders_due_spoken_uses_now_passed_to_run(db):
    """due_spoken depends on the `now` given to run: the same row is 'today' on 10 Oct."""
    add_pending("call the lab", "2026-10-10T17:00:00+05:30")

    out = tools.run("list_reminders", {}, NOW)

    assert [r["due_spoken"] for r in out["reminders"]] == ["5 pm"]


def test_fr10_list_reminders_due_spoken_converts_utc_stored_value(db, fixed_now):
    """A row stored with a Z offset is formatted in Kolkata time: 11:30Z is 5 pm IST."""
    add_pending("x", "2026-10-09T11:30:00Z")

    out = tools.run("list_reminders", {}, fixed_now)

    assert [r["due_spoken"] for r in out["reminders"]] == ["5 pm"]


def test_fr10_cancel_reminder_result_has_no_due_spoken(db, fixed_now):
    """cancel_reminder is unchanged: exactly {id, text, due_at, status}, no due_spoken."""
    added = add_pending("call the lab", DUE_A)

    out = tools.run("cancel_reminder", {"id": added["id"]}, fixed_now)

    assert set(out) == {"id", "text", "due_at", "status"}


@pytest.mark.parametrize(
    ("due_at", "now", "prefix"),
    [
        (
            "2026-10-09T17:00:00+05:30",
            datetime(2026, 10, 9, 14, 0, tzinfo=IST),
            "Reminder",
        ),
        (
            "2026-10-10T17:00:00+05:30",
            datetime(2026, 10, 9, 14, 0, tzinfo=IST),
            "Reminder",
        ),
        (
            "2026-10-09T17:30:00+05:30",
            datetime(2026, 10, 9, 18, 0, tzinfo=IST),
            "Missed reminder",
        ),
        (
            "2026-10-10T17:00:00+05:30",
            datetime(2026, 10, 11, 9, 0, tzinfo=IST),
            "Missed reminder",
        ),
    ],
    ids=["fresh-today", "fresh-other-day", "missed-today", "missed-other-day"],
)
def test_fr10_reminder_text_is_prefix_due_spoken_and_text(db, due_at, now, prefix):
    """reminder_text equals '<Reminder|Missed reminder>, ' + due_spoken + ': ' + text, so both
    use the same time wording."""
    added = tools.run(
        "add_reminder",
        {"text": "call the lab", "due_at": due_at},
        datetime(2026, 10, 9, 14, 0, tzinfo=IST),
    )
    stored = {k: added[k] for k in ("id", "text", "due_at")}

    spoken = tools.reminder_text(stored, now)

    assert spoken == f"{prefix}, {added['due_spoken']}: call the lab"


# --- log_concept (FR-23) ---

LORA_SUMMARY = "LoRA fine-tunes a model by training small low-rank adapter matrices."


def test_fr23_declares_log_concept_with_required_name_and_summary():
    """DECLARATIONS has one log_concept entry whose schema requires string 'name' and 'summary'."""
    decl = declaration("log_concept")
    assert decl["description"]
    schema = decl["parameters_json_schema"]
    assert schema["type"] == "object"
    assert schema["properties"]["name"]["type"] == "string"
    assert schema["properties"]["summary"]["type"] == "string"
    assert "name" in schema["required"]
    assert "summary" in schema["required"]


def test_fr23_log_concept_returns_new_result_and_stores_one_concept(db, fixed_now):
    """run('log_concept') returns {name, summary, status 'new', new True} and stores the concept."""
    out = tools.run("log_concept", {"name": "LoRA", "summary": LORA_SUMMARY}, fixed_now)

    assert set(out) == {"name", "summary", "status", "new"}
    assert out["name"] == "LoRA"
    assert out["summary"] == LORA_SUMMARY
    assert out["status"] == "new"
    assert out["new"] is True
    assert store.concept_names() == ["LoRA"]


def test_fr23_log_concept_same_name_other_case_is_not_new(db, fixed_now):
    """Logging 'lora' after 'LoRA' returns new False and still stores one concept."""
    tools.run("log_concept", {"name": "LoRA", "summary": LORA_SUMMARY}, fixed_now)

    out = tools.run(
        "log_concept", {"name": "lora", "summary": "Low-rank adaptation."}, fixed_now
    )

    assert "error" not in out
    assert out["new"] is False
    assert len(store.concept_names()) == 1


@pytest.mark.parametrize(
    "args",
    [
        {"summary": LORA_SUMMARY},
        {"name": "", "summary": LORA_SUMMARY},
        {"name": "   ", "summary": LORA_SUMMARY},
        {"name": 5, "summary": LORA_SUMMARY},
        {"name": None, "summary": LORA_SUMMARY},
        {"name": "LoRA"},
        {"name": "LoRA", "summary": ""},
        {"name": "LoRA", "summary": "   "},
        {"name": "LoRA", "summary": 5},
    ],
    ids=[
        "missing-name",
        "empty-name",
        "whitespace-name",
        "non-string-name",
        "none-name",
        "missing-summary",
        "empty-summary",
        "whitespace-summary",
        "non-string-summary",
    ],
)
def test_fr23_log_concept_bad_arguments_return_error_and_store_nothing(
    db, fixed_now, args
):
    """A missing, empty, blank or non-string name or summary returns {error} and stores nothing."""
    out = tools.run("log_concept", args, fixed_now)

    assert isinstance(out.get("error"), str) and out["error"]
    assert store.concept_names() == []


# --- learned_this_week (FR-25) ---


def log_concept_at(name, when):
    store.log_concept(name, "summary", when.isoformat(timespec="seconds"))


def test_fr25_declares_learned_this_week_without_required_parameters():
    """DECLARATIONS has one learned_this_week entry that requires no parameters."""
    decl = declaration("learned_this_week")
    assert decl["description"]
    schema = decl["parameters_json_schema"]
    assert schema["type"] == "object"
    assert not schema.get("required")


def test_fr25_learned_this_week_counts_recent_and_names_five_newest(db):
    """With 7 concepts first asked in the last 7 days and 2 older, count is 7 and names are the 5 newest, newest first."""
    assert config.LEARNED_DAYS == 7
    assert config.LEARNED_MAX_NAMES == 5
    # Inserted out of order so that insertion order cannot pass for recency.
    for i in (3, 0, 6, 1, 5, 2, 4):
        log_concept_at(f"recent{i}", NOW - timedelta(days=i, hours=1))
    log_concept_at("older8", NOW - timedelta(days=8))
    log_concept_at("older9", NOW - timedelta(days=9))

    out = tools.run("learned_this_week", {}, NOW)

    assert out == {
        "count": 7,
        "names": ["recent0", "recent1", "recent2", "recent3", "recent4"],
    }


def test_fr25_learned_this_week_none_returns_zero_and_no_names(db):
    """With no concepts in the last 7 days, the result is {count: 0, names: []}."""
    assert tools.run("learned_this_week", {}, NOW) == {"count": 0, "names": []}
    log_concept_at("older", NOW - timedelta(days=8))
    assert tools.run("learned_this_week", {}, NOW) == {"count": 0, "names": []}


def test_fr25_learned_this_week_ignores_extra_arguments(db):
    """learned_this_week takes no arguments: extra ones are ignored."""
    log_concept_at("recent", NOW - timedelta(days=1))

    out = tools.run("learned_this_week", {"junk": 1}, NOW)

    assert out == {"count": 1, "names": ["recent"]}


def test_fr25_learned_this_week_uses_config_values(db, monkeypatch):
    """The window and the name limit come from config: LEARNED_MAX_NAMES=2 gives 2 names, LEARNED_DAYS=3 narrows the count."""
    for i in range(5):
        log_concept_at(f"c{i}", NOW - timedelta(days=i, hours=1))
    monkeypatch.setattr(config, "LEARNED_MAX_NAMES", 2)

    out = tools.run("learned_this_week", {}, NOW)

    assert out == {"count": 5, "names": ["c0", "c1"]}

    monkeypatch.setattr(config, "LEARNED_DAYS", 3)

    out = tools.run("learned_this_week", {}, NOW)

    assert out == {"count": 3, "names": ["c0", "c1"]}


# --- start_quiz (FR-24) ---


def log_quiz_concept(name, day):
    store.log_concept(name, f"summary {name}", f"2026-10-{day:02d}T10:00:00+05:30")


def test_fr24_declares_start_quiz_without_parameters():
    """DECLARATIONS has one start_quiz entry that takes no arguments."""
    decl = declaration("start_quiz")
    assert decl["description"]
    schema = decl["parameters_json_schema"]
    assert schema["type"] == "object"
    assert not schema.get("properties")
    assert not schema.get("required")


def test_fr24_start_quiz_picks_three_oldest_new_and_asks_the_first(db):
    """With 4 new concepts and 1 wrong one, count is 3, the question names the oldest new one, and the session holds those 3 in order."""
    log_quiz_concept("wrongone", 1)
    store.set_quiz_result("wrongone", False, "2026-10-02T10:00:00+05:30")
    for name, day in (("n6", 6), ("n3", 3), ("n5", 5), ("n4", 4)):
        log_quiz_concept(name, day)

    out = tools.run("start_quiz", {}, NOW)

    assert out == {"count": 3, "question": "Explain n3 in one sentence."}
    state = session.quiz(NOW)
    assert [c["name"] for c in state["concepts"]] == ["n3", "n4", "n5"]
    assert state["index"] == 0
    assert state["right"] == 0


def test_fr24_start_quiz_with_no_concepts_returns_zero_and_starts_nothing(db):
    """With no concepts, start_quiz returns {count: 0, question: ''} and no quiz is running."""
    out = tools.run("start_quiz", {}, NOW)

    assert out == {"count": 0, "question": ""}
    assert session.quiz(NOW) is None


def test_fr24_start_quiz_with_only_right_concepts_returns_zero(db):
    """Concepts answered right are not quizzed again: count 0, empty question, no quiz running."""
    log_quiz_concept("done", 1)
    store.set_quiz_result("done", True, "2026-10-02T10:00:00+05:30")

    out = tools.run("start_quiz", {}, NOW)

    assert out == {"count": 0, "question": ""}
    assert session.quiz(NOW) is None


def test_fr24_start_quiz_ignores_extra_arguments(db):
    """start_quiz takes no arguments: extra ones are ignored and nothing raises."""
    log_quiz_concept("LoRA", 1)

    out = tools.run("start_quiz", {"junk": 1}, NOW)

    assert out == {"count": 1, "question": "Explain LoRA in one sentence."}


def test_fr24_quiz_question_template():
    """quiz_question(name) is 'Explain <name> in one sentence.' from config.QUIZ_QUESTION."""
    assert config.QUIZ_QUESTION == "Explain {name} in one sentence."
    assert tools.quiz_question("LoRA") == "Explain LoRA in one sentence."


def test_fr24_start_quiz_question_comes_from_config_template(db, monkeypatch):
    """The question is built from config.QUIZ_QUESTION, not hard-coded."""
    monkeypatch.setattr(config, "QUIZ_QUESTION", "Define {name}.")
    log_quiz_concept("LoRA", 1)

    out = tools.run("start_quiz", {}, NOW)

    assert out == {"count": 1, "question": "Define LoRA."}
    assert tools.quiz_question("Softmax") == "Define Softmax."


@pytest.mark.parametrize(
    ("right", "total", "text"),
    [(2, 3, "2 of 3 right"), (0, 3, "0 of 3 right")],
)
def test_fr24_quiz_score_text(right, total, text):
    """The end of a quiz speaks the score as '<right> of <total> right'."""
    assert tools.quiz_score_text(right, total) == text


# --- remember (FR-33) ---

MEMORY_TYPES = {"fact", "project", "preference", "session"}
LORA_POINT = "Studying LoRA fine-tuning"
LORA_REPEAT = "I am studying LoRA fine tuning"
THIRTEEN_WORDS = (
    "one two three four five six seven eight nine ten eleven twelve thirteen"
)


def memory_count(db_path):
    con = sqlite3.connect(db_path)
    try:
        return con.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    finally:
        con.close()


def memory_rows_in_db(db_path):
    con = sqlite3.connect(db_path)
    try:
        return con.execute("SELECT text, created_at FROM memories").fetchall()
    finally:
        con.close()


def test_fr33_declares_remember_with_required_text_and_type_enum():
    """DECLARATIONS has one remember entry requiring string 'text' and string 'type' (enum of the four types)."""
    decl = declaration("remember")
    assert decl["description"]
    schema = decl["parameters_json_schema"]
    assert schema["type"] == "object"
    assert schema["properties"]["text"]["type"] == "string"
    assert schema["properties"]["type"]["type"] == "string"
    assert set(schema["properties"]["type"]["enum"]) == MEMORY_TYPES
    assert len(schema["properties"]["type"]["enum"]) == 4
    assert "text" in schema["required"]
    assert "type" in schema["required"]


def test_fr33_remember_stores_exactly_one_row(db, fixed_now):
    """One remember call stores exactly one row, never two."""
    tools.run("remember", {"text": LORA_POINT, "type": "fact"}, fixed_now)

    assert memory_count(db) == 1


def test_fr33_remember_returns_id_text_type_created_at_new(db, fixed_now):
    """remember returns exactly {id, text, type, created_at, new} with the stored values and new True."""
    out = tools.run("remember", {"text": LORA_POINT, "type": "project"}, fixed_now)

    assert set(out) == {"id", "text", "type", "created_at", "new"}
    assert out["text"] == LORA_POINT
    assert out["type"] == "project"
    assert out["created_at"] == FIXED_ISO
    assert out["new"] is True
    assert memory_rows_in_db(db) == [(LORA_POINT, FIXED_ISO)]


def test_fr33_remember_strips_the_text(db, fixed_now):
    """The stored and returned text is stripped of surrounding whitespace."""
    out = tools.run(
        "remember", {"text": "  " + LORA_POINT + "  ", "type": "fact"}, fixed_now
    )

    assert out["text"] == LORA_POINT
    assert memory_rows_in_db(db)[0][0] == LORA_POINT


@pytest.mark.parametrize("mem_type", sorted(MEMORY_TYPES))
def test_fr33_remember_accepts_each_of_the_four_types(db, fixed_now, mem_type):
    """Each of fact, project, preference and session is accepted and returned as given."""
    out = tools.run("remember", {"text": LORA_POINT, "type": mem_type}, fixed_now)

    assert out["type"] == mem_type
    assert out["new"] is True
    assert memory_count(db) == 1


def test_fr33_remember_repeat_returns_existing_item_not_new(db):
    """A near-verbatim repeat returns new False and the original item (id, text, type, created_at)."""
    first = tools.run("remember", {"text": LORA_POINT, "type": "fact"}, NOW)
    later = NOW + timedelta(hours=1)

    out = tools.run("remember", {"text": LORA_REPEAT, "type": "fact"}, later)

    assert set(out) == {"id", "text", "type", "created_at", "new"}
    assert out["new"] is False
    assert out["id"] == first["id"]
    assert out["text"] == LORA_POINT
    assert out["type"] == first["type"]
    assert out["created_at"] == first["created_at"]


def test_fr33_remember_repeat_stores_no_second_row(db):
    """After a repeat the table still has one row, with the original created_at."""
    first = tools.run("remember", {"text": LORA_POINT, "type": "fact"}, NOW)

    tools.run(
        "remember", {"text": LORA_REPEAT, "type": "fact"}, NOW + timedelta(hours=1)
    )

    assert memory_rows_in_db(db) == [(LORA_POINT, first["created_at"])]


def test_fr33_remember_two_different_points_store_two_rows(db, fixed_now):
    """Two different points are both new and store two rows."""
    a = tools.run("remember", {"text": LORA_POINT, "type": "fact"}, fixed_now)
    b = tools.run(
        "remember",
        {"text": "Prefers short spoken answers", "type": "preference"},
        fixed_now,
    )

    assert a["new"] is True
    assert b["new"] is True
    assert a["id"] != b["id"]
    assert memory_count(db) == 2


@pytest.mark.parametrize(
    "args",
    [
        {"text": "", "type": "fact"},
        {"text": "   ", "type": "fact"},
        {"type": "fact"},
        {"text": 5, "type": "fact"},
        {"text": None, "type": "fact"},
        {"text": LORA_POINT},
        {"text": LORA_POINT, "type": None},
        {"text": LORA_POINT, "type": 5},
        {"text": LORA_POINT, "type": ""},
        {"text": LORA_POINT, "type": "hobby"},
        {"text": THIRTEEN_WORDS, "type": "fact"},
    ],
    ids=[
        "empty-text",
        "blank-text",
        "missing-text",
        "non-string-text",
        "none-text",
        "missing-type",
        "none-type",
        "non-string-type",
        "empty-type",
        "unknown-type",
        "thirteen-words",
    ],
)
def test_fr33_remember_bad_arguments_return_error_and_store_nothing(
    db, fixed_now, args
):
    """Empty text, an unknown type or text over the word limit returns only {error} and stores nothing."""
    out = tools.run("remember", args, fixed_now)

    assert list(out) == ["error"]
    assert isinstance(out["error"], str) and out["error"]
    assert memory_count(db) == 0


def test_fr33_remember_twelve_words_is_accepted(db, fixed_now):
    """Text of exactly config.MEMORY_MAX_WORDS (12) words is stored."""
    assert config.MEMORY_MAX_WORDS == 12
    text = " ".join(THIRTEEN_WORDS.split()[:12])

    out = tools.run("remember", {"text": text, "type": "fact"}, fixed_now)

    assert out["new"] is True
    assert memory_count(db) == 1


def test_fr33_remember_word_limit_error_mentions_the_limit(db, fixed_now):
    """The over-limit error mentions the word limit so Gemini can shorten the point."""
    out = tools.run("remember", {"text": THIRTEEN_WORDS, "type": "fact"}, fixed_now)

    assert str(config.MEMORY_MAX_WORDS) in out["error"]


# --- search_memories (FR-36, FR-37, FR-38) ---

SEARCH_KEYS = {"id", "text", "type", "created_at"}


def mem_on(text, day, hour=9):
    return store.add_memory(
        text, store.FACT, f"2026-09-{day:02d}T{hour:02d}:00:00+05:30"
    )


def test_fr36_declares_search_memories_with_three_optional_strings():
    """DECLARATIONS has one search_memories entry with string properties query, since and until, none required."""
    decl = declaration("search_memories")
    assert decl["description"]
    schema = decl["parameters_json_schema"]
    assert schema["type"] == "object"
    for name in ("query", "since", "until"):
        assert schema["properties"][name]["type"] == "string"
    assert not schema.get("required")


def test_fr37_query_with_twelve_matches_gives_count_twelve_and_five_items(
    db, fixed_now
):
    """With a query matching 12 of 50 stored items, count is 12 and items holds 5."""
    for n in range(12):
        store.add_memory(f"annotation note number {n}", store.FACT, FIXED_ISO)
    for n in range(38):
        store.add_memory(f"unrelated gardening item {n}", store.FACT, FIXED_ISO)

    out = tools.run("search_memories", {"query": "annotation"}, fixed_now)

    assert set(out) == {"count", "items"}
    assert out["count"] == 12
    assert len(out["items"]) == config.MEMORY_RECALL_MAX == 5


def test_fr37_best_match_is_first_among_the_items(db, fixed_now):
    """The item matching more query words comes first in items."""
    for n in range(11):
        store.add_memory(f"annotation note number {n}", store.FACT, FIXED_ISO)
    best = store.add_memory(
        "annotation guidelines for the dataset", store.FACT, FIXED_ISO
    )

    out = tools.run("search_memories", {"query": "annotation dataset"}, fixed_now)

    assert out["items"][0]["id"] == best["id"]
    assert out["count"] == 12


def test_fr37_fifty_matching_items_still_give_five_items(db, fixed_now):
    """With 50 matching items stored, count is 50 and items still holds at most 5."""
    for n in range(50):
        store.add_memory(f"annotation note number {n}", store.FACT, FIXED_ISO)

    out = tools.run("search_memories", {"query": "annotation"}, fixed_now)

    assert out["count"] == 50
    assert len(out["items"]) == 5


def test_fr37_query_with_no_match_gives_zero_and_no_items(db, fixed_now):
    """A query matching nothing gives count 0 and no items."""
    store.add_memory("The annotation plan is ready", store.FACT, FIXED_ISO)

    out = tools.run("search_memories", {"query": "quantum chromodynamics"}, fixed_now)

    assert out == {"count": 0, "items": []}


def test_fr37_items_have_exactly_the_four_keys(db, fixed_now):
    """Each item, from a query and from a list, carries exactly id, text, type and created_at."""
    store.add_memory("The annotation plan is ready", store.PROJECT, FIXED_ISO)

    searched = tools.run("search_memories", {"query": "annotation"}, fixed_now)
    listed = tools.run("search_memories", {}, fixed_now)

    for out in (searched, listed):
        assert len(out["items"]) == 1
        assert set(out["items"][0]) == SEARCH_KEYS
        assert out["items"][0]["text"] == "The annotation plan is ready"
        assert out["items"][0]["type"] == "project"
        assert out["items"][0]["created_at"] == FIXED_ISO


def test_fr36_no_query_with_eight_items_gives_count_eight_and_five_newest(
    db, fixed_now
):
    """With no query and 8 items, count is 8 and items are the 5 most recent, newest first."""
    # Inserted out of order so that insertion order cannot pass for recency.
    ids = {
        n: mem_on(f"separate point number {n}", n)["id"]
        for n in (4, 1, 7, 3, 8, 2, 6, 5)
    }

    out = tools.run("search_memories", {}, fixed_now)

    assert set(out) == {"count", "items"}
    assert out["count"] == 8
    assert [m["id"] for m in out["items"]] == [ids[n] for n in (8, 7, 6, 5, 4)]


def test_fr36_no_items_stored_gives_count_zero_and_empty_items(db, fixed_now):
    """With nothing stored, count is 0 and items is empty."""
    assert tools.run("search_memories", {}, fixed_now) == {"count": 0, "items": []}
    assert tools.run("search_memories", {"query": "annotation"}, fixed_now) == {
        "count": 0,
        "items": [],
    }


@pytest.mark.parametrize("query", [None, "", "   "], ids=["none", "empty", "blank"])
def test_fr36_none_or_blank_query_behaves_as_no_query(db, fixed_now, query):
    """A None, empty or whitespace query lists the 5 most recent items with the total count."""
    ids = [mem_on(f"separate point number {n}", n)["id"] for n in range(1, 9)]

    out = tools.run("search_memories", {"query": query}, fixed_now)

    assert out["count"] == 8
    assert [m["id"] for m in out["items"]] == ids[::-1][:5]


def test_fr38_no_query_window_returns_only_in_window_items_and_total(db, fixed_now):
    """With since and until and no query, items are only those in the window and count is the in-window total."""
    for n in range(1, 13):
        mem_on(f"separate point number {n}", n)

    out = tools.run(
        "search_memories", {"since": "2026-09-03", "until": "2026-09-11"}, fixed_now
    )

    assert out["count"] == 8
    assert [m["created_at"][:10] for m in out["items"]] == [
        f"2026-09-{d:02d}" for d in (10, 9, 8, 7, 6)
    ]


def test_fr38_query_window_counts_only_in_window_matches(db, fixed_now):
    """With a query and a window, count and items cover only the in-window matches."""
    for n in range(1, 10):
        mem_on(f"annotation note number {n}", n)
    mem_on("gardening note inside the window", 5)

    out = tools.run(
        "search_memories",
        {"query": "annotation", "since": "2026-09-02", "until": "2026-09-08"},
        fixed_now,
    )

    assert out["count"] == 6
    assert len(out["items"]) == 5
    assert all(
        "2026-09-02" <= m["created_at"][:10] < "2026-09-08" for m in out["items"]
    )
    assert all("annotation" in m["text"] for m in out["items"])


def test_fr38_date_only_since_is_local_midnight(db, fixed_now):
    """since='2026-09-01' is midnight in the local zone: an item at 02:00+05:30 that day counts, 23:59:59 the day before does not."""
    early = store.add_memory(
        "annotation early morning", store.FACT, "2026-09-01T02:00:00+05:30"
    )
    store.add_memory("annotation last second", store.FACT, "2026-08-31T23:59:59+05:30")

    listed = tools.run("search_memories", {"since": "2026-09-01"}, fixed_now)
    searched = tools.run(
        "search_memories", {"query": "annotation", "since": "2026-09-01"}, fixed_now
    )

    for out in (listed, searched):
        assert out["count"] == 1
        assert [m["id"] for m in out["items"]] == [early["id"]]


@pytest.mark.parametrize("bad", [5, 1.5, True, ["2026-09-01"], {"a": 1}])
def test_fr38_non_string_since_and_until_are_ignored(db, fixed_now, bad):
    """A since or until that is not a string is ignored: no filter, no error."""
    for n in range(1, 4):
        mem_on(f"annotation note number {n}", n)

    listed = tools.run("search_memories", {"since": bad, "until": bad}, fixed_now)
    searched = tools.run(
        "search_memories",
        {"query": "annotation", "since": bad, "until": bad},
        fixed_now,
    )

    assert listed["count"] == searched["count"] == 3
    assert len(listed["items"]) == len(searched["items"]) == 3


@pytest.mark.parametrize("bad", [5, 1.5, True, ["annotation"], {"a": 1}])
def test_fr37_non_string_query_returns_only_an_error(db, fixed_now, bad):
    """A query that is neither None nor a string returns only {error: <reason>}."""
    store.add_memory("The annotation plan is ready", store.FACT, FIXED_ISO)

    out = tools.run("search_memories", {"query": bad}, fixed_now)

    assert list(out) == ["error"]
    assert isinstance(out["error"], str) and out["error"]


def test_fr36_search_memories_does_not_change_the_row_count(db, fixed_now):
    """The tool never writes: the memories table has the same rows after searching and listing."""
    for n in range(1, 7):
        mem_on(f"annotation note number {n}", n)
    before = memory_rows_in_db(db)

    tools.run("search_memories", {"query": "annotation"}, fixed_now)
    tools.run("search_memories", {}, fixed_now)
    tools.run("search_memories", {"query": 5}, fixed_now)

    assert memory_count(db) == 6
    assert memory_rows_in_db(db) == before
