"""Tool declarations and dispatch tests (FR-5, FR-7). search.search is faked: no network."""

import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from server import config, search, store, tools

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
    """run('add_reminder') returns exactly {id, text, due_at} and stores one pending reminder."""
    out = tools.run(
        "add_reminder",
        {"text": "call the lab", "due_at": "2026-10-10T17:00:00+05:30"},
        fixed_now,
    )

    assert set(out) == {"id", "text", "due_at"}
    assert out["text"] == "call the lab"
    assert out["due_at"] == "2026-10-10T17:00:00+05:30"
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

    assert set(out) == {"id", "text", "due_at"}
    assert out["due_at"] == FIXED_ISO
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
    assert {k: rows[0][k] for k in ("id", "text", "due_at")} == added


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
    """list_reminders returns pending reminders as {id, text, due_at}, ordered by due_at."""
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
        assert set(r) == {"id", "text", "due_at"}
    assert [r["text"] for r in out["reminders"]] == ["early", "middle", "late"]
    assert [r["due_at"] for r in out["reminders"]] == [DUE_A, DUE_B, DUE_C]


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
