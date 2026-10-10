import inspect
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

import server.main
from server import config
from server.main import app

# Values returned by the fakes in conftest.py
FAKE_TRANSCRIPT = "what time is it"
FAKE_ANSWER = "It is two PM."
FAKE_TTS_WAV = b"RIFF-fake-wav-bytes"
FIXED_NOW = datetime(2026, 10, 9, 14, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

client = TestClient(app)


def test_fr18_health_returns_ok_and_model():
    """FR-18: GET /health returns 200 {"status": "ok", "model": "<model name>"}."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model": config.LLM_MODEL}


def test_fr4_lifespan_loads_stt_once(fake_stages):
    """FR-4: the lifespan calls stt.load() once at startup, never per request.

    The `with` form is used here because it is what runs the lifespan; it is
    safe because stt.load and tts.load are faked, so no model is loaded.
    """
    with TestClient(app) as c:
        first = c.get("/health")
        second = c.get("/health")

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(fake_stages["stt_load"]) == 1
    assert len(fake_stages["tts_load"]) == 1


def test_fr11_lifespan_loads_tts_once(fake_stages):
    """FR-11: the lifespan calls tts.load() exactly once, not per request."""
    with TestClient(app) as c:
        c.get("/health")
        c.get("/health")

    assert len(fake_stages["tts_load"]) == 1


def test_fr11_query_valid_wav_returns_tts_audio(fake_stages, silent_wav):
    """FR-11: a valid WAV upload returns 200 audio/wav with the TTS bytes."""
    response = client.post(
        "/query", files={"audio": ("q.wav", silent_wav, "audio/wav")}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == FAKE_TTS_WAV


def test_fr11_query_runs_stages_in_order(fake_stages, silent_wav):
    """FR-11: stt -> llm -> tts; llm gets transcript and now, tts gets the answer."""
    client.post("/query", files={"audio": ("q.wav", silent_wav, "audio/wav")})
    assert fake_stages["order"] == ["stt", "llm", "tts"]
    assert fake_stages["stt"] == [silent_wav]
    assert fake_stages["llm"] == [(FAKE_TRANSCRIPT, FIXED_NOW)]
    assert fake_stages["tts"] == [FAKE_ANSWER]


def test_fr11_query_handler_is_plain_def():
    """FR-11: POST /query is a plain def so /health stays responsive."""
    assert not inspect.iscoroutinefunction(server.main.query)


def test_fr11_now_is_aware_in_configured_timezone():
    """FR-11: main.now() returns a timezone-aware datetime in config.TIMEZONE."""
    value = server.main.now()
    assert value.tzinfo is not None
    assert value.utcoffset() == datetime.now(ZoneInfo(config.TIMEZONE)).utcoffset()


def test_fr18_default_host_is_localhost():
    """FR-18: the server binds to the configured host, which is 127.0.0.1."""
    assert config.HOST == "127.0.0.1"
