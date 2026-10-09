from fastapi.testclient import TestClient

from server import config
from server.main import app

client = TestClient(app)


def test_fr18_health_returns_ok_and_model():
    """FR-18: GET /health returns 200 {"status": "ok", "model": "<model name>"}."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model": config.LLM_MODEL}


def test_fr18_default_host_is_localhost():
    """FR-18: the server binds to the configured host, which is 127.0.0.1."""
    assert config.HOST == "127.0.0.1"
