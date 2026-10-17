import io
import wave
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

FAKE_TRANSCRIPT = "what time is it"
FAKE_ANSWER = "It is two PM."
FAKE_TTS_WAV = b"RIFF-fake-wav-bytes"
FIXED_NOW = datetime(2026, 10, 9, 14, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def make_wav(seconds: int = 1) -> bytes:
    """Silent 16 kHz mono 16-bit WAV, built in code."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000 * seconds)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _clean_session():
    """No test leaks session turns into another."""
    from server import session

    session.reset()
    yield
    session.reset()


@pytest.fixture
def silent_wav() -> bytes:
    return make_wav()


@pytest.fixture
def db(monkeypatch, tmp_path):
    """Temporary SQLite file with the tables created."""
    from server import store

    path = tmp_path / "test.db"
    monkeypatch.setattr("server.config.DB_PATH", path)
    store.init()
    return path


@pytest.fixture
def fixed_now(monkeypatch) -> datetime:
    monkeypatch.setattr("server.main.now", lambda: FIXED_NOW)
    return FIXED_NOW


@pytest.fixture
def fake_stages(monkeypatch, fixed_now) -> dict:
    """Fake every stage and record calls in order.

    calls["order"] lists stage names; calls["stt"], ["llm"], ["tts"], and
    ["stt_load"], ["tts_load"] hold the arguments of each call.
    calls["transcript"] is what stt "hears"; calls["grade"] holds (name,
    summary, answer) per llm.grade call; calls["grade_result"] is the dict
    grade returns, or an Exception instance to make it raise.
    """
    calls = {
        "order": [],
        "stt": [],
        "llm": [],
        "llm_turns": [],
        "llm_images": [],
        "tts": [],
        "stt_load": [],
        "tts_load": [],
        "transcript": FAKE_TRANSCRIPT,
        "grade": [],
        "grade_result": {"correct": True, "feedback": "Right."},
    }

    def transcribe(wav):
        calls["order"].append("stt")
        calls["stt"].append(wav)
        return calls["transcript"]

    def grade(name, summary, answer):
        calls["order"].append("grade")
        calls["grade"].append((name, summary, answer))
        result = calls["grade_result"]
        if isinstance(result, Exception):
            raise result
        return dict(result)

    def ask(question, now, turns=(), image=None):
        calls["order"].append("llm")
        calls["llm"].append((question, now))
        calls["llm_turns"].append(list(turns))
        calls["llm_images"].append(image)
        return FAKE_ANSWER, False, []

    def synthesize(text):
        calls["order"].append("tts")
        calls["tts"].append(text)
        return FAKE_TTS_WAV

    monkeypatch.setattr("server.stt.transcribe", transcribe)
    monkeypatch.setattr("server.llm.ask", ask)
    monkeypatch.setattr("server.llm.grade", grade)
    monkeypatch.setattr("server.tts.synthesize", synthesize)
    monkeypatch.setattr("server.stt.load", lambda: calls["stt_load"].append(1))
    monkeypatch.setattr("server.tts.load", lambda: calls["tts_load"].append(1))
    return calls
