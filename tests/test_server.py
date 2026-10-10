import inspect
import io
import json
import wave
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
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


@pytest.fixture(autouse=True)
def log_path(tmp_path, monkeypatch):
    """Point the query log at a temporary file so tests never touch logs/."""
    path = tmp_path / "queries.jsonl"
    monkeypatch.setattr(config, "LOG_PATH", path)
    return path


def _log_lines(path) -> list[dict]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


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


def _wav(rate: int = 16000, channels: int = 1, width: int = 2, frames: int = 16000):
    """Silent WAV with the given format, built in code."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x00" * width * channels * frames)
    return buf.getvalue()


def _assert_rejected_then_ok(response, expected_error, calls, silent_wav):
    assert response.status_code == 400
    assert response.json() == {"error": expected_error}
    assert calls["order"] == []
    again = client.post("/query", files={"audio": ("q.wav", silent_wav, "audio/wav")})
    assert again.status_code == 200


def test_fr16_audio_missing_returns_400(fake_stages, silent_wav):
    """FR-16: no `audio` field -> 400 {"error": "audio missing"}, not 422; no stage runs."""
    response = client.post("/query")
    _assert_rejected_then_ok(response, "audio missing", fake_stages, silent_wav)


def test_fr16_audio_missing_with_other_multipart_field(fake_stages, silent_wav):
    """FR-16: multipart body without `audio` -> 400 {"error": "audio missing"}."""
    response = client.post(
        "/query", files={"other": ("o.wav", silent_wav, "audio/wav")}
    )
    _assert_rejected_then_ok(response, "audio missing", fake_stages, silent_wav)


def test_fr16_audio_empty_zero_bytes(fake_stages, silent_wav):
    """FR-16: a 0-byte audio file -> 400 {"error": "audio empty"}."""
    response = client.post("/query", files={"audio": ("q.wav", b"", "audio/wav")})
    _assert_rejected_then_ok(response, "audio empty", fake_stages, silent_wav)


def test_fr16_audio_empty_zero_frames(fake_stages, silent_wav):
    """FR-16: a valid WAV header with 0 frames -> 400 {"error": "audio empty"}."""
    response = client.post(
        "/query", files={"audio": ("q.wav", _wav(frames=0), "audio/wav")}
    )
    _assert_rejected_then_ok(response, "audio empty", fake_stages, silent_wav)


def test_fr16_audio_not_a_readable_wav(fake_stages, silent_wav):
    """FR-16: bytes that are not a WAV -> 400 {"error": "audio is not a readable WAV"}."""
    response = client.post(
        "/query", files={"audio": ("q.wav", b"not a wav", "audio/wav")}
    )
    _assert_rejected_then_ok(
        response, "audio is not a readable WAV", fake_stages, silent_wav
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rate": 44100},
        {"channels": 2},
        {"width": 1},
    ],
    ids=["44.1kHz", "stereo", "8-bit"],
)
def test_fr16_audio_wrong_format(fake_stages, silent_wav, kwargs):
    """FR-16: a WAV that is not 16 kHz mono 16-bit -> 400 with the format error."""
    response = client.post(
        "/query", files={"audio": ("q.wav", _wav(**kwargs), "audio/wav")}
    )
    _assert_rejected_then_ok(
        response, "audio must be 16 kHz mono 16-bit", fake_stages, silent_wav
    )


@pytest.mark.parametrize("transcript", ["", "   "], ids=["empty", "whitespace"])
def test_fr16_empty_transcript_returns_no_speech(
    fake_stages, silent_wav, monkeypatch, transcript
):
    """FR-16: empty transcript -> 400 {"error": "no speech detected"} before llm.ask."""
    answers = iter([transcript])

    def transcribe(wav):
        fake_stages["order"].append("stt")
        return next(answers, "what time is it")

    monkeypatch.setattr("server.stt.transcribe", transcribe)
    response = client.post(
        "/query", files={"audio": ("q.wav", silent_wav, "audio/wav")}
    )
    assert response.status_code == 400
    assert response.json() == {"error": "no speech detected"}
    assert fake_stages["order"] == ["stt"]
    assert fake_stages["llm"] == []
    assert fake_stages["tts"] == []
    again = client.post("/query", files={"audio": ("q.wav", silent_wav, "audio/wav")})
    assert again.status_code == 200


STAGE_FAKES = {
    "stt": "server.stt.transcribe",
    "llm": "server.llm.ask",
    "tts": "server.tts.synthesize",
}


def _post_query(silent_wav):
    return client.post("/query", files={"audio": ("q.wav", silent_wav, "audio/wav")})


def _make_stage_raise(monkeypatch, fake_stages, stage, exc):
    """Replace one stage fake with one that records its call, then raises exc.

    Returns the normal fake so the test can restore it.
    """
    module_name, attr = STAGE_FAKES[stage].rsplit(".", 1)
    module = __import__(module_name, fromlist=[attr])
    normal = getattr(module, attr)

    def failing(*args):
        fake_stages["order"].append(stage)
        raise exc

    monkeypatch.setattr(STAGE_FAKES[stage], failing)
    return normal


@pytest.mark.parametrize("stage", ["stt", "llm", "tts"])
def test_fr16_stage_failure_returns_500_and_stops(
    fake_stages, silent_wav, monkeypatch, stage
):
    """FR-16: a stage failure -> 500 {"error": "<stage>: <reason>"}; later stages
    do not run; the next valid request returns 200."""
    normal = _make_stage_raise(monkeypatch, fake_stages, stage, RuntimeError("boom"))
    response = _post_query(silent_wav)
    assert response.status_code == 500
    assert response.json() == {"error": f"{stage}: boom"}
    order = ["stt", "llm", "tts"]
    assert fake_stages["order"] == order[: order.index(stage) + 1]

    monkeypatch.setattr(STAGE_FAKES[stage], normal)
    fake_stages["order"].clear()
    again = _post_query(silent_wav)
    assert again.status_code == 200
    assert again.content == FAKE_TTS_WAV


def test_fr16_llm_too_many_tool_rounds_message(fake_stages, silent_wav, monkeypatch):
    """FR-16: llm raising "too many tool rounds" -> 500 {"error": "llm: too many tool rounds"}."""
    _make_stage_raise(
        monkeypatch, fake_stages, "llm", RuntimeError("too many tool rounds")
    )
    response = _post_query(silent_wav)
    assert response.status_code == 500
    assert response.json() == {"error": "llm: too many tool rounds"}
    assert fake_stages["order"] == ["stt", "llm"]


def test_fr16_empty_exception_message_uses_type_name(
    fake_stages, silent_wav, monkeypatch
):
    """FR-16: an exception with no message -> reason is the exception type name."""
    _make_stage_raise(monkeypatch, fake_stages, "llm", TimeoutError())
    response = _post_query(silent_wav)
    assert response.status_code == 500
    assert response.json() == {"error": "llm: TimeoutError"}


def test_fr16_error_redacts_api_keys(fake_stages, silent_wav, monkeypatch):
    """FR-16: configured Gemini and Tavily key values never appear in the response;
    they are replaced by "[redacted]"."""
    gemini_key = "fake-gemini-key-AAA111"
    tavily_key = "fake-tavily-key-BBB222"
    monkeypatch.setattr(config, "GEMINI_API_KEY", gemini_key)
    monkeypatch.setattr(config, "TAVILY_API_KEY", tavily_key)
    _make_stage_raise(
        monkeypatch,
        fake_stages,
        "llm",
        RuntimeError(f"bad {gemini_key} and {tavily_key}"),
    )
    response = _post_query(silent_wav)
    assert response.status_code == 500
    assert gemini_key not in response.text
    assert tavily_key not in response.text
    assert "[redacted]" in response.text


def test_fr16_error_reason_truncated_to_max_chars(fake_stages, silent_wav, monkeypatch):
    """FR-16: the reason is cut to config.ERROR_MAX_CHARS characters."""
    monkeypatch.setattr(config, "ERROR_MAX_CHARS", 20)
    _make_stage_raise(monkeypatch, fake_stages, "llm", RuntimeError("x" * 100))
    response = _post_query(silent_wav)
    assert response.status_code == 500
    assert response.json() == {"error": "llm: " + "x" * 20}


def test_fr16_key_straddling_cut_point_is_not_leaked(
    fake_stages, silent_wav, monkeypatch
):
    """FR-16: redaction happens before truncation, so a key that straddles the
    cut point leaves no key fragment in the response."""
    key = "SECRETKEY123"
    monkeypatch.setattr(config, "ERROR_MAX_CHARS", 20)
    monkeypatch.setattr(config, "GEMINI_API_KEY", key)
    monkeypatch.setattr(config, "TAVILY_API_KEY", "")
    _make_stage_raise(monkeypatch, fake_stages, "llm", RuntimeError("x" * 15 + key))
    response = _post_query(silent_wav)
    assert response.status_code == 500
    assert "SECRE" not in response.text
    reason = response.json()["error"].removeprefix("llm: ")
    assert len(reason) == 20


def test_fr16_run_stage_success_returns_result_and_times():
    """FR-16: run_stage returns fn's result and sets timings[name] to int ms >= 0."""
    timings: dict = {}
    result = server.main.run_stage("stt", timings, lambda a, b: a + b, 1, 2)
    assert result == 3
    assert isinstance(timings["stt"], int)
    assert timings["stt"] >= 0


def test_fr16_run_stage_failure_raises_stage_failed_and_times():
    """FR-16: run_stage wraps a failure in StageFailed and still sets timings[name]."""
    timings: dict = {}

    def boom():
        raise RuntimeError("boom")

    with pytest.raises(server.main.StageFailed):
        server.main.run_stage("tts", timings, boom)
    assert isinstance(timings["tts"], int)
    assert timings["tts"] >= 0


def test_fr17_success_writes_one_complete_line(fake_stages, silent_wav, log_path):
    """FR-17: a successful /query writes exactly one JSONL line with question,
    answer, per-stage timings (stt, llm, tts), searched, tool_calls and error."""
    response = _post_query(silent_wav)
    assert response.status_code == 200
    lines = _log_lines(log_path)
    assert len(lines) == 1
    line = lines[0]
    assert line["question"] == FAKE_TRANSCRIPT
    assert line["answer"] == FAKE_ANSWER
    assert set(line["timings_ms"]) == {"stt", "llm", "tts"}
    assert all(isinstance(v, int) and v >= 0 for v in line["timings_ms"].values())
    assert line["searched"] is False
    assert line["tool_calls"] == []
    assert line["error"] is None


@pytest.mark.parametrize(
    "files, error",
    [
        (None, "audio missing"),
        ({"audio": ("q.wav", b"", "audio/wav")}, "audio empty"),
        (
            {"audio": ("q.wav", b"not a wav", "audio/wav")},
            "audio is not a readable WAV",
        ),
        (
            {"audio": ("q.wav", _wav(rate=44100), "audio/wav")},
            "audio must be 16 kHz mono 16-bit",
        ),
    ],
    ids=["missing", "zero-bytes", "not-a-wav", "wrong-format"],
)
def test_fr17_audio_400_writes_one_line(fake_stages, log_path, files, error):
    """FR-17: each 400 audio problem writes exactly one line with the reason as
    error and empty question, answer, timings and tool calls."""
    response = client.post("/query", files=files) if files else client.post("/query")
    assert response.status_code == 400
    assert response.json() == {"error": error}
    lines = _log_lines(log_path)
    assert len(lines) == 1
    line = lines[0]
    assert line["question"] is None
    assert line["answer"] is None
    assert line["timings_ms"] == {}
    assert line["searched"] is False
    assert line["tool_calls"] == []
    assert line["error"] == error


def test_fr17_no_speech_400_logs_only_stt_timing(
    fake_stages, silent_wav, monkeypatch, log_path
):
    """FR-17: a no-speech 400 writes one line whose timings_ms has only 'stt'
    and error 'no speech detected'."""
    monkeypatch.setattr("server.stt.transcribe", lambda wav: "   ")
    response = _post_query(silent_wav)
    assert response.status_code == 400
    assert response.json() == {"error": "no speech detected"}
    lines = _log_lines(log_path)
    assert len(lines) == 1
    line = lines[0]
    assert set(line["timings_ms"]) == {"stt"}
    assert line["answer"] is None
    assert line["error"] == "no speech detected"


@pytest.mark.parametrize("stage", ["stt", "llm", "tts"])
def test_fr17_stage_failure_logs_one_line_with_timing(
    fake_stages, silent_wav, monkeypatch, log_path, stage
):
    """FR-17: a failing stage still writes exactly one line with error
    '<stage>: boom' and the failed stage's timing; a tts failure keeps the answer."""
    _make_stage_raise(monkeypatch, fake_stages, stage, RuntimeError("boom"))
    response = _post_query(silent_wav)
    assert response.status_code == 500
    assert response.json() == {"error": f"{stage}: boom"}
    lines = _log_lines(log_path)
    assert len(lines) == 1
    line = lines[0]
    assert line["error"] == f"{stage}: boom"
    order = ["stt", "llm", "tts"]
    assert set(line["timings_ms"]) == set(order[: order.index(stage) + 1])
    assert all(isinstance(v, int) for v in line["timings_ms"].values())
    if stage == "stt":
        assert line["question"] is None
    else:
        assert line["question"] == FAKE_TRANSCRIPT
    if stage == "tts":
        assert line["answer"] == FAKE_ANSWER
    else:
        assert line["answer"] is None


def test_fr17_llm_failure_logs_exception_tool_calls(
    fake_stages, silent_wav, monkeypatch, log_path
):
    """FR-17: when the llm exception has a tool_calls list, the line logs it."""
    calls = [{"name": "web_search", "args": {"query": "x"}, "ok": True}]
    exc = RuntimeError("deadline exceeded")
    exc.tool_calls = calls
    _make_stage_raise(monkeypatch, fake_stages, "llm", exc)
    response = _post_query(silent_wav)
    assert response.status_code == 500
    assert response.json() == {"error": "llm: deadline exceeded"}
    lines = _log_lines(log_path)
    assert len(lines) == 1
    assert lines[0]["tool_calls"] == calls


def test_fr17_llm_failure_without_tool_calls_logs_empty_list(
    fake_stages, silent_wav, monkeypatch, log_path
):
    """FR-17: an llm exception without a tool_calls attribute logs tool_calls []."""
    _make_stage_raise(monkeypatch, fake_stages, "llm", RuntimeError("boom"))
    _post_query(silent_wav)
    lines = _log_lines(log_path)
    assert len(lines) == 1
    assert lines[0]["tool_calls"] == []


def test_fr17_api_keys_absent_from_log_and_response(
    fake_stages, silent_wav, monkeypatch, log_path
):
    """FR-17: a stage exception containing the Gemini and Tavily keys leaves
    neither key in the log file nor in the response body."""
    gemini_key = "fake-gemini-key-AAA111"
    tavily_key = "fake-tavily-key-BBB222"
    monkeypatch.setattr(config, "GEMINI_API_KEY", gemini_key)
    monkeypatch.setattr(config, "TAVILY_API_KEY", tavily_key)
    _make_stage_raise(
        monkeypatch,
        fake_stages,
        "llm",
        RuntimeError(f"bad {gemini_key} and {tavily_key}"),
    )
    response = _post_query(silent_wav)
    assert response.status_code == 500
    raw = log_path.read_text(encoding="utf-8")
    assert len(_log_lines(log_path)) == 1
    for key in (gemini_key, tavily_key):
        assert key not in raw
        assert key not in response.text


def test_fr17_two_requests_write_two_lines(fake_stages, silent_wav, log_path):
    """FR-17: every request appends exactly one line; two requests give two."""
    _post_query(silent_wav)
    _post_query(silent_wav)
    assert len(_log_lines(log_path)) == 2


def test_fr18_default_host_is_localhost():
    """FR-18: the server binds to the configured host, which is 127.0.0.1."""
    assert config.HOST == "127.0.0.1"
