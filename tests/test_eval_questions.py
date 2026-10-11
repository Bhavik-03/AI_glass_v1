"""Validates the frozen eval set eval/questions.json (M7-T2; FR-5, FR-8, FR-9, FR-10)."""

import json
import re
from pathlib import Path

import pytest

QUESTIONS_PATH = Path(__file__).resolve().parent.parent / "eval" / "questions.json"

TOOLS = {
    "web_search",
    "add_note",
    "list_notes",
    "add_reminder",
    "list_reminders",
    "cancel_reminder",
}
GROUPS = ["general", "notes", "reminders"]
PASS_KEYS = {
    "tools",
    "searched",
    "answer_all",
    "answer_some",
    "answer_fact",
    "note_added",
    "notes_total",
    "reminder_added",
    "reminder_cancelled",
    "reminders_pending",
}
ROW_KEYS = {"id", "group", "spoken", "expected_transcript", "pass"}
ACTION_ONLY_KEYS = {
    "note_added",
    "notes_total",
    "reminder_added",
    "reminder_cancelled",
    "reminders_pending",
}
DUE_AT = re.compile(r"^(tomorrow|day_after_tomorrow) ([01]\d|2[0-3]):[0-5]\d$")


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))


def _group(rows, name):
    return [r for r in rows if r["group"] == name]


def _tools(row):
    return row["pass"].get("tools", [])


def _is_word_list(value) -> bool:
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(w, str) and w for w in value)
    )


def test_fr5_thirty_rows_ten_per_group_in_order(rows):
    """30 rows; groups contiguous in order general, notes, reminders, 10 each."""
    assert isinstance(rows, list) and len(rows) == 30
    assert [r["group"] for r in rows] == [g for g in GROUPS for _ in range(10)]


def test_fr5_ids_unique_strings(rows):
    """Each row has a unique non-empty string id."""
    ids = [r["id"] for r in rows]
    assert all(isinstance(i, str) and i for i in ids)
    assert len(set(ids)) == len(ids)


def test_fr5_row_fields_present_and_typed(rows):
    """Each row has exactly id, group, spoken, expected_transcript, pass."""
    for r in rows:
        assert set(r) == ROW_KEYS, r.get("id")
        assert r["group"] in GROUPS
        assert isinstance(r["spoken"], str) and r["spoken"].strip()
        assert isinstance(r["expected_transcript"], str)
        assert isinstance(r["pass"], dict)


def test_fr5_expected_transcript_is_normalised_spoken(rows):
    """expected_transcript equals spoken lowercased, punctuation removed, whitespace collapsed."""
    for r in rows:
        no_punct = re.sub(r"[^\w\s]", "", r["spoken"].lower())
        assert r["expected_transcript"] == " ".join(no_punct.split()), r["id"]


def test_fr5_spoken_has_no_digits(rows):
    """No digit in spoken text (Whisper writes numerals, breaking transcript comparison)."""
    for r in rows:
        assert not re.search(r"[0-9]", r["spoken"]), r["id"]


def test_fr5_spoken_does_not_wait_for_reminder(rows):
    """No row's spoken text mentions waiting for a reminder to become due."""
    for r in rows:
        assert "wait" not in r["spoken"].lower(), r["id"]


def test_fr5_pass_rule_keys_and_types(rows):
    """Pass rules use only allowed keys with the right shapes."""
    for r in rows:
        p = r["pass"]
        assert set(p) <= PASS_KEYS, r["id"]
        if "tools" in p:
            assert isinstance(p["tools"], list)
            assert set(p["tools"]) <= TOOLS, r["id"]
        if "searched" in p:
            assert isinstance(p["searched"], bool)
        if "answer_all" in p:
            aa = p["answer_all"]
            assert isinstance(aa, list) and aa
            for alts in aa:
                assert _is_word_list(alts), r["id"]
                assert all(w == w.lower() for w in alts), r["id"]
        if "answer_some" in p:
            s = p["answer_some"]
            assert set(s) == {"min", "words"}, r["id"]
            assert _is_word_list(s["words"])
            assert isinstance(s["min"], int) and not isinstance(s["min"], bool)
            assert 1 <= s["min"] <= len(s["words"]), r["id"]
        if "answer_fact" in p:
            assert isinstance(p["answer_fact"], str)
            re.compile(p["answer_fact"])
        if "note_added" in p:
            assert _is_word_list(p["note_added"]), r["id"]
        if "notes_total" in p:
            assert isinstance(p["notes_total"], int)
            assert not isinstance(p["notes_total"], bool)
        if "reminder_cancelled" in p:
            assert _is_word_list(p["reminder_cancelled"]), r["id"]
        if "reminders_pending" in p:
            assert isinstance(p["reminders_pending"], int)
            assert not isinstance(p["reminders_pending"], bool)


def test_fr10_every_row_checks_the_answer(rows):
    """Every row has answer_all or answer_some (action rows: the repeat-back check)."""
    for r in rows:
        assert "answer_all" in r["pass"] or "answer_some" in r["pass"], r["id"]


def test_fr5_general_rows_have_no_action_checks(rows):
    """General rows carry no note/reminder state checks."""
    for r in _group(rows, "general"):
        assert not (set(r["pass"]) & ACTION_ONLY_KEYS), r["id"]


def test_fr8_general_seven_stable_three_live(rows):
    """General: exactly 3 searched rows (with web_search), exactly 7 with tools == []."""
    general = _group(rows, "general")
    live = [r for r in general if r["pass"].get("searched") is True]
    assert len(live) == 3
    for r in live:
        assert "web_search" in _tools(r), r["id"]
    stable = [r for r in general if r["pass"].get("tools") == []]
    assert len(stable) == 7
    assert not ({r["id"] for r in live} & {r["id"] for r in stable})


def test_fr8_live_rows_include_pune_weather_and_news(rows):
    """Live questions include weather in Pune and a recent-news search."""
    live = [r for r in _group(rows, "general") if r["pass"].get("searched") is True]
    texts = [r["spoken"].lower() for r in live]
    assert any("weather" in t and "pune" in t for t in texts)
    assert any("news" in t for t in texts)


def test_fr8_live_answer_fact_regexes(rows):
    """answer_fact only on live rows, and at least 2 of the 3 live rows have it."""
    general = _group(rows, "general")
    for r in rows:
        if "answer_fact" in r["pass"]:
            assert r["pass"].get("searched") is True, r["id"]
    live = [r for r in general if r["pass"].get("searched") is True]
    assert sum("answer_fact" in r["pass"] for r in live) >= 2


def test_fr9_notes_add_rows_come_first(rows):
    """Notes: first 5 rows add a note (tools == [add_note], note_added)."""
    for r in _group(rows, "notes")[:5]:
        assert _tools(r) == ["add_note"], r["id"]
        assert "note_added" in r["pass"], r["id"]


def test_fr9_notes_list_rows_last_with_total(rows):
    """Notes: last 5 rows use list_notes, add nothing, and expect notes_total == 5."""
    for r in _group(rows, "notes")[5:]:
        assert "list_notes" in _tools(r), r["id"]
        assert "note_added" not in r["pass"], r["id"]
        assert r["pass"].get("notes_total") == 5, r["id"]


def test_fr10_reminders_add_rows_come_first(rows):
    """Reminders: first 5 rows add a reminder (tools == [add_reminder], reminder_added)."""
    for r in _group(rows, "reminders")[:5]:
        assert _tools(r) == ["add_reminder"], r["id"]
        assert "reminder_added" in r["pass"], r["id"]


def test_fr10_reminders_later_rows_list_or_cancel(rows):
    """Reminders: rows after the adds use list_reminders and/or cancel_reminder only."""
    for r in _group(rows, "reminders")[5:]:
        tools = _tools(r)
        assert tools and set(tools) <= {"list_reminders", "cancel_reminder"}, r["id"]
        assert "reminder_added" not in r["pass"], r["id"]


def test_fr10_at_least_two_list_and_two_cancel_rows(rows):
    """Reminders: at least 2 list rows and at least 2 cancel rows."""
    rem = _group(rows, "reminders")
    assert sum("list_reminders" in _tools(r) for r in rem) >= 2
    assert sum("cancel_reminder" in _tools(r) for r in rem) >= 2


def test_fr10_cancel_rows_after_a_list_and_have_cancelled_words(rows):
    """A cancel row has list_reminders in an earlier row and reminder_cancelled."""
    rem = _group(rows, "reminders")
    for i, r in enumerate(rem):
        if "cancel_reminder" in _tools(r):
            assert "reminder_cancelled" in r["pass"], r["id"]
            assert any("list_reminders" in _tools(p) for p in rem[:i]), r["id"]


def test_fr10_add_before_list_or_cancel_within_group(rows):
    """No reminder_added row appears after a list or cancel row in its group."""
    for name in ("notes", "reminders"):
        seen_other = False
        for r in _group(rows, name):
            tools = set(_tools(r))
            if tools & {
                "list_notes",
                "list_reminders",
                "cancel_reminder",
            }:
                seen_other = True
            if "note_added" in r["pass"] or "reminder_added" in r["pass"]:
                assert not seen_other, r["id"]


def test_fr10_reminder_due_is_future_form(rows):
    """Every reminder_added has words and a due of '<tomorrow|day_after_tomorrow> HH:MM' or in_minutes > 0."""
    added = [r for r in rows if "reminder_added" in r["pass"]]
    assert len(added) >= 5
    for r in added:
        ra = r["pass"]["reminder_added"]
        assert set(ra) == {"words", "due"}, r["id"]
        assert _is_word_list(ra["words"]), r["id"]
        due = ra["due"]
        assert isinstance(due, dict) and len(due) == 1, r["id"]
        if "at" in due:
            assert isinstance(due["at"], str) and DUE_AT.match(due["at"]), r["id"]
        else:
            assert set(due) == {"in_minutes"}, r["id"]
            m = due["in_minutes"]
            assert isinstance(m, int) and not isinstance(m, bool) and m > 0, r["id"]
