"""Tool declarations and dispatch tests (FR-5, FR-7). search.search is faked: no network."""

from datetime import datetime
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
