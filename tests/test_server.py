from fastapi.testclient import TestClient

from server import config
from server.main import app

client = TestClient(app)


def test_fr18_health_returns_ok_and_model():
    """FR-18: GET /health returns 200 {"status": "ok", "model": "<model name>"}."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model": config.LLM_MODEL}


def test_fr4_lifespan_loads_stt_once(monkeypatch):
    """FR-4: the lifespan calls stt.load() once at startup, never per request.

    The `with` form is used here because it is what runs the lifespan; it is
    safe because stt.load is faked, so no model is loaded.
    """
    calls = []
    monkeypatch.setattr("server.stt.load", lambda: calls.append(1))

    with TestClient(app) as c:
        first = c.get("/health")
        second = c.get("/health")

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(calls) == 1


def test_fr18_default_host_is_localhost():
    """FR-18: the server binds to the configured host, which is 127.0.0.1."""
    assert config.HOST == "127.0.0.1"
