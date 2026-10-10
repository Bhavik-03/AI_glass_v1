"""Web search module tests (FR-5). A fake Tavily client is used: no network or key."""

import pytest

from server import config, search


def install_fake(monkeypatch, response=None, error=None):
    calls = {"inits": [], "searches": []}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            calls["inits"].append(kwargs)

        def search(self, query, **kwargs):
            calls["searches"].append((query, kwargs))
            if error:
                raise error
            return response

    monkeypatch.setattr(search, "TavilyClient", FakeClient)
    return calls


def test_fr5_uses_config_for_key_and_request(monkeypatch):
    """search() passes the key, basic depth, result count and timeout from config."""
    monkeypatch.setattr(config, "TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(config, "SEARCH_MAX_RESULTS", 3)
    monkeypatch.setattr(config, "SEARCH_TIMEOUT_S", 2)
    calls = install_fake(monkeypatch, response={"results": []})

    search.search("weather in Pune")

    assert calls["inits"] == [{"api_key": "test-key"}]
    assert calls["searches"] == [
        ("weather in Pune", {"search_depth": "basic", "max_results": 3, "timeout": 2})
    ]


def test_fr5_returns_only_title_url_content_in_order(monkeypatch):
    """search() returns [{title, url, content}] in Tavily's order, extra keys dropped."""
    monkeypatch.setattr(config, "TAVILY_API_KEY", "test-key")
    response = {
        "results": [
            {"title": "A", "url": "http://a", "content": "ca", "score": 0.9},
            {"title": "B", "url": "http://b", "content": "cb", "score": 0.5, "raw": 1},
        ]
    }
    install_fake(monkeypatch, response=response)

    assert search.search("q") == [
        {"title": "A", "url": "http://a", "content": "ca"},
        {"title": "B", "url": "http://b", "content": "cb"},
    ]


def test_fr5_empty_key_raises_without_creating_client(monkeypatch):
    """An empty TAVILY_API_KEY raises and the Tavily client is never constructed."""
    monkeypatch.setattr(config, "TAVILY_API_KEY", "")
    calls = install_fake(monkeypatch, response={"results": []})

    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        search.search("q")
    assert calls["inits"] == []


def test_fr5_client_error_propagates(monkeypatch):
    """A failure from the Tavily client is raised, not swallowed."""
    monkeypatch.setattr(config, "TAVILY_API_KEY", "test-key")
    install_fake(monkeypatch, error=TimeoutError("timed out"))

    with pytest.raises(TimeoutError):
        search.search("q")


def test_fr5_no_results_returns_empty_list(monkeypatch):
    """No results from Tavily gives an empty list."""
    monkeypatch.setattr(config, "TAVILY_API_KEY", "test-key")
    install_fake(monkeypatch, response={"results": []})

    assert search.search("q") == []
