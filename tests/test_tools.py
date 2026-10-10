"""Tool declarations and dispatch tests (FR-5, FR-7). search.search is faked: no network."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from server import config, search, tools

NOW = datetime(2026, 10, 10, 9, 0, tzinfo=ZoneInfo(config.TIMEZONE))


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
    assert [d["name"] for d in tools.DECLARATIONS] == ["web_search"]
    decl = tools.DECLARATIONS[0]
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
