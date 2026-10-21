import inspect
import io
import json
import wave
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import server.main
from server import config, profile
from server.main import app

# Values returned by the fakes in conftest.py
FAKE_TRANSCRIPT = "what time is it"
FAKE_ANSWER = "It is two PM."
FAKE_TTS_WAV = b"RIFF-fake-wav-bytes"
FIXED_NOW = datetime(2026, 10, 9, 14, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_profile(tmp_path, monkeypatch):
    """The lifespan loads the profile: never the real data/profile.json, and no state
    left behind for other tests."""
    monkeypatch.setattr(config, "PROFILE_VALUES_PATH", tmp_path / "no_profile.json")
    monkeypatch.setattr(profile, "_slots", [])
    monkeypatch.setattr(profile, "_values", {})


@pytest.fixture(autouse=True)
def log_path(tmp_path, monkeypatch):
    """Point the query log at a temporary file so tests never touch logs/."""
    path = tmp_path / "queries.jsonl"
    monkeypatch.setattr(config, "LOG_PATH", path)
    return path


@pytest.fixture(autouse=True)
def _temp_db(db):
    """Every test here uses a temporary database: the lifespan calls store.init()."""
    return db


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

    def failing(*args, **kwargs):
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
    assert line["session_continued"] is False
    assert line["image_sent"] is False


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
    assert line["session_continued"] is False
    assert line["image_sent"] is False


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
    assert line["session_continued"] is False
    assert line["image_sent"] is False


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


TURN = {"question": FAKE_TRANSCRIPT, "answer": FAKE_ANSWER}


@pytest.fixture
def clock(monkeypatch):
    """Mutable clock: clock.t is what server.main.now() returns."""

    class Clock:
        t = FIXED_NOW

        def at(self, seconds: int):
            self.t = FIXED_NOW + timedelta(seconds=seconds)

    c = Clock()
    monkeypatch.setattr("server.main.now", lambda: c.t)
    return c


def test_fr21_first_query_sends_no_turns(fake_stages, silent_wav, log_path):
    """FR-21: the first query has no saved turns: llm.ask gets none and the
    log line has session_continued false."""
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["llm_turns"] == [[]]
    assert _log_lines(log_path)[0]["session_continued"] is False


def test_fr21_second_query_within_120s_gets_previous_turn(
    fake_stages, silent_wav, log_path, clock
):
    """FR-21: a query within 120 s of the last answer passes the saved turn to
    llm.ask and the log line has session_continued true."""
    _post_query(silent_wav)
    clock.at(60)
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["llm_turns"][1] == [TURN]
    lines = _log_lines(log_path)
    assert lines[0]["session_continued"] is False
    assert lines[1]["session_continued"] is True


def test_fr21_turns_passed_oldest_first_and_grow(fake_stages, silent_wav, clock):
    """FR-21: each successful query adds one turn; the next llm.ask gets all
    saved turns, oldest first."""
    for i in range(3):
        clock.at(i * 10)
        _post_query(silent_wav)
    assert [len(t) for t in fake_stages["llm_turns"]] == [0, 1, 2]
    assert fake_stages["llm_turns"][2] == [TURN, TURN]


def test_fr21_second_query_after_121s_starts_new_session(
    fake_stages, silent_wav, log_path, clock
):
    """FR-21: a query 121 s after the last answer gets no turns and the log
    line has session_continued false."""
    _post_query(silent_wav)
    clock.at(121)
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["llm_turns"][1] == []
    assert _log_lines(log_path)[1]["session_continued"] is False


@pytest.mark.parametrize("stage", ["llm", "tts"])
def test_fr21_failed_query_adds_no_turn(
    fake_stages, silent_wav, monkeypatch, log_path, clock, stage
):
    """FR-21: a 500 adds no turn: the next query sees no turns from it."""
    normal = _make_stage_raise(monkeypatch, fake_stages, stage, RuntimeError("boom"))
    clock.at(10)
    assert _post_query(silent_wav).status_code == 500
    assert _log_lines(log_path)[0]["session_continued"] is False
    monkeypatch.setattr(STAGE_FAKES[stage], normal)
    clock.at(20)
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["llm_turns"][-1] == []
    assert _log_lines(log_path)[1]["session_continued"] is False


def test_fr21_failed_query_does_not_extend_window(
    fake_stages, silent_wav, monkeypatch, clock
):
    """FR-21: a failed query does not extend the 120 s: success at T0, failure
    at T0+100 s, a query at T0+130 s gets no turns."""
    _post_query(silent_wav)
    normal = _make_stage_raise(monkeypatch, fake_stages, "tts", RuntimeError("boom"))
    clock.at(100)
    assert _post_query(silent_wav).status_code == 500
    monkeypatch.setattr(STAGE_FAKES["tts"], normal)
    clock.at(130)
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["llm_turns"][-1] == []


def test_fr21_failed_query_keeps_earlier_turns(
    fake_stages, silent_wav, monkeypatch, clock
):
    """FR-21: a failure inside the window leaves the saved turns unchanged."""
    _post_query(silent_wav)
    normal = _make_stage_raise(monkeypatch, fake_stages, "llm", RuntimeError("boom"))
    clock.at(30)
    assert _post_query(silent_wav).status_code == 500
    monkeypatch.setattr(STAGE_FAKES["llm"], normal)
    clock.at(60)
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["llm_turns"][-1] == [TURN]


def test_fr21_audio_400_adds_no_turn(fake_stages, silent_wav, log_path):
    """FR-21 / FR-17: a 400 audio error logs session_continued false and adds no
    turn."""
    assert client.post("/query").status_code == 400
    assert _log_lines(log_path)[0]["session_continued"] is False
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["llm_turns"] == [[]]


def test_fr21_no_speech_400_adds_no_turn(
    fake_stages, silent_wav, monkeypatch, log_path, clock
):
    """FR-21 / FR-17: a no-speech 400 logs session_continued false, adds no
    turn and does not extend the window."""
    _post_query(silent_wav)
    monkeypatch.setattr("server.stt.transcribe", lambda wav: "  ")
    clock.at(100)
    assert _post_query(silent_wav).status_code == 400
    assert _log_lines(log_path)[1]["session_continued"] is False
    monkeypatch.setattr("server.stt.transcribe", lambda wav: FAKE_TRANSCRIPT)
    clock.at(130)
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["llm_turns"][-1] == []


def test_fr17_failed_continued_query_logs_session_continued_true(
    fake_stages, silent_wav, monkeypatch, log_path, clock
):
    """FR-17: a 500 whose question used saved turns logs session_continued true."""
    _post_query(silent_wav)
    _make_stage_raise(monkeypatch, fake_stages, "tts", RuntimeError("boom"))
    clock.at(30)
    assert _post_query(silent_wav).status_code == 500
    assert _log_lines(log_path)[1]["session_continued"] is True


def test_fr22_reset_with_no_session_returns_ok():
    """FR-22: POST /session/reset with no session returns 200 {"status": "ok"}."""
    response = client.post("/session/reset")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_fr22_reset_clears_session_for_next_query(
    fake_stages, silent_wav, log_path, clock
):
    """FR-22: after a query, reset returns 200 {"status": "ok"}; the next query
    within 120 s gets no turns and logs session_continued false."""
    _post_query(silent_wav)
    clock.at(30)
    response = client.post("/session/reset")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    clock.at(60)
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["llm_turns"][-1] == []
    assert _log_lines(log_path)[-1]["session_continued"] is False


def test_fr22_reset_twice_returns_ok_both_times():
    """FR-22: calling POST /session/reset twice returns 200 {"status": "ok"} both times."""
    for _ in range(2):
        response = client.post("/session/reset")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


PAST = "2026-10-09T13:00:00+05:30"
EQUAL = "2026-10-09T14:00:00+05:30"
FUTURE = "2026-10-09T15:00:00+05:30"
CREATED = "2026-10-09T12:00:00+05:30"


def _add(text: str, due_at: str) -> int:
    """Create a reminder through store and return its id."""
    from server import store

    result = store.add_reminder(text, due_at, CREATED)
    return result["id"] if isinstance(result, dict) else result


def test_fr12_lifespan_calls_store_init_once(fake_stages, monkeypatch):
    """FR-12: the lifespan calls store.init() exactly once at startup."""
    calls = []
    monkeypatch.setattr("server.store.init", lambda: calls.append(1))
    with TestClient(app) as c:
        c.get("/health")
        c.get("/health")
    assert len(calls) == 1


def test_fr12_due_returns_keys_oldest_first(fixed_now):
    """FR-12: 200 [{id, text, due_at}] of pending reminders with due_at <= now
    (equal counts), oldest first."""
    later = _add("later", PAST.replace("13:00", "13:30"))
    equal = _add("equal", EQUAL)
    oldest = _add("oldest", PAST)
    response = client.get("/reminders/due")
    assert response.status_code == 200
    body = response.json()
    assert [r["id"] for r in body] == [oldest, later, equal]
    assert all(set(r) == {"id", "text", "due_at"} for r in body)
    assert [r["text"] for r in body] == ["oldest", "later", "equal"]
    assert body[0]["due_at"] == PAST
    assert body[2]["due_at"] == EQUAL


def test_fr12_due_204_empty_body_when_no_reminders(fixed_now):
    """FR-12: 204 with an empty body when nothing is due (no reminders at all)."""
    response = client.get("/reminders/due")
    assert response.status_code == 204
    assert response.content == b""


def test_fr12_due_204_empty_body_when_only_future(fixed_now):
    """FR-12: 204 with an empty body when only future reminders exist."""
    _add("future", FUTURE)
    response = client.get("/reminders/due")
    assert response.status_code == 204
    assert response.content == b""


def test_fr12_due_excludes_future_delivered_cancelled(fixed_now):
    """FR-12: future, delivered and cancelled reminders are never listed."""
    from server import store

    pending = _add("pending", PAST)
    _add("future", FUTURE)
    delivered = _add("delivered", PAST)
    cancelled = _add("cancelled", PAST)
    store.ack(delivered)
    store.cancel(cancelled)
    response = client.get("/reminders/due")
    assert response.status_code == 200
    assert [r["id"] for r in response.json()] == [pending]


def test_fr12_polling_twice_returns_same_list_and_keeps_status(fixed_now):
    """FR-12: polling again without an ack returns the same reminders; calling
    /reminders/due does not change any reminder's status."""
    from server import store

    first_id = _add("a", PAST)
    second_id = _add("b", EQUAL)
    before = store.list_pending()
    first = client.get("/reminders/due")
    second = client.get("/reminders/due")
    after = store.list_pending()
    assert [r["id"] for r in after] == [first_id, second_id]
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert [r["id"] for r in second.json()] == [first_id, second_id]
    assert after == before


def test_fr12_due_handler_is_plain_def():
    """FR-12: GET /reminders/due is a plain def so sqlite runs in the thread pool."""
    routes = [r for r in app.routes if getattr(r, "path", None) == "/reminders/due"]
    assert len(routes) == 1
    assert not inspect.iscoroutinefunction(routes[0].endpoint)


def test_fr12_health_still_ok_with_lifespan(fake_stages):
    """FR-12: /health still returns 200 with the model after the lifespan change."""
    with TestClient(app) as c:
        response = c.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model": config.LLM_MODEL}


def test_fr12_due_and_health_write_no_log_line(fixed_now, log_path):
    """FR-12: /reminders/due (200 and 204) and /health write no JSONL line."""
    client.get("/reminders/due")
    _add("a", PAST)
    client.get("/reminders/due")
    client.get("/health")
    assert _log_lines(log_path) == []


NOT_FOUND = {"error": "reminder not found"}


def _pending_ids() -> list[int]:
    from server import store

    return [r["id"] for r in store.list_pending()]


def test_fr14_ack_due_reminder_returns_ok_and_leaves_due(fixed_now):
    """FR-14: ack of a due reminder gives 200 {"status": "ok"}; it is then absent
    from /reminders/due and from the pending list."""
    rid = _add("call the lab", PAST)
    assert [r["id"] for r in client.get("/reminders/due").json()] == [rid]
    response = client.post(f"/reminders/{rid}/ack")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert client.get("/reminders/due").status_code == 204
    assert rid not in _pending_ids()


def test_fr14_ack_twice_returns_200_both_times(fixed_now):
    """FR-14: acking again gives 200 {"status": "ok"}; it stays out of /reminders/due."""
    rid = _add("call the lab", PAST)
    first = client.post(f"/reminders/{rid}/ack")
    second = client.post(f"/reminders/{rid}/ack")
    assert first.status_code == 200
    assert first.json() == {"status": "ok"}
    assert second.status_code == 200
    assert second.json() == {"status": "ok"}
    assert client.get("/reminders/due").status_code == 204


def test_fr14_ack_unknown_id_returns_404(fixed_now):
    """FR-14: unknown id gives 404 {"error": "reminder not found"}."""
    response = client.post("/reminders/999/ack")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_fr14_ack_future_reminder_marks_it_delivered(fixed_now):
    """FR-14: ack is the only way to deliver; a future pending reminder can be
    acked (200) and is then no longer pending."""
    rid = _add("later", FUTURE)
    assert rid in _pending_ids()
    response = client.post(f"/reminders/{rid}/ack")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert rid not in _pending_ids()


def test_fr14_ack_cancelled_reminder_returns_200(fixed_now):
    """FR-14: any existing reminder can be acked; a cancelled one gives 200
    {"status": "ok"} and is neither due nor pending."""
    from server import store

    rid = _add("cancelled", PAST)
    store.cancel(rid)
    response = client.post(f"/reminders/{rid}/ack")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert client.get("/reminders/due").status_code == 204
    assert rid not in _pending_ids()


def test_fr14_ack_leaves_other_due_reminder_untouched(fixed_now):
    """FR-14: acking one reminder does not change another due reminder."""
    acked = _add("acked", PAST)
    other = _add("other", EQUAL)
    response = client.post(f"/reminders/{acked}/ack")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    due = client.get("/reminders/due")
    assert due.status_code == 200
    assert [r["id"] for r in due.json()] == [other]
    assert _pending_ids() == [other]


@pytest.mark.parametrize(
    "bad_id",
    ["abc", "1.5", "-1", "1_0", "%20", "%D9%A3", "1" + "0" * 30, "9" * 5000],
    ids=[
        "letters",
        "decimal",
        "negative",
        "underscore",
        "space",
        "arabic-digit",
        "huge",
        "over-4300-digits",
    ],
)
def test_fr14_ack_non_integer_id_returns_404(fixed_now, bad_id):
    """FR-14: a non-integer or out-of-range id (not ASCII digits, or too large
    for SQLite) gives 404 {"error": "reminder not found"}, never 422 or 500, and
    acks nothing: the existing reminder 1 stays pending."""
    rid = _add("keep me", PAST)
    assert rid == 1  # fresh temporary database
    response = client.post(f"/reminders/{bad_id}/ack")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert _pending_ids() == [rid]
    assert [r["id"] for r in client.get("/reminders/due").json()] == [rid]


def test_fr14_ack_writes_no_log_line(fixed_now, log_path):
    """FR-14: the ack endpoint (200 and 404) writes no JSONL line."""
    rid = _add("a", PAST)
    assert client.post(f"/reminders/{rid}/ack").status_code == 200
    assert client.post("/reminders/999/ack").status_code == 404
    assert _log_lines(log_path) == []


def test_fr14_ack_handler_is_plain_def():
    """FR-14: POST /reminders/{reminder_id}/ack is a plain def so sqlite runs in
    the thread pool."""
    routes = [
        r
        for r in app.routes
        if getattr(r, "path", None) == "/reminders/{reminder_id}/ack"
        and "POST" in getattr(r, "methods", set())
    ]
    assert len(routes) == 1
    assert not inspect.iscoroutinefunction(routes[0].endpoint)


def test_fr18_default_host_is_localhost():
    """FR-18: the server binds to the configured host, which is 127.0.0.1."""
    assert config.HOST == "127.0.0.1"


def _audio_ok(fake_stages, due_at: str, expected_text: str):
    rid = _add("call the lab", due_at)
    response = client.get(f"/reminders/{rid}/audio")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == FAKE_TTS_WAV
    assert fake_stages["tts"] == [expected_text]


def test_fr13_audio_fresh_reminder_age_zero(fake_stages):
    """FR-13: a reminder due exactly now is spoken as "Reminder, 2 pm: ..." and
    returned as audio/wav made by tts.synthesize."""
    _audio_ok(fake_stages, EQUAL, "Reminder, 2 pm: call the lab")


def test_fr13_audio_fresh_reminder_59_seconds_old(fake_stages):
    """FR-13: a reminder 59 s old is still fresh: "Reminder, 1:59 pm: ..."."""
    _audio_ok(
        fake_stages, "2026-10-09T13:59:01+05:30", "Reminder, 1:59 pm: call the lab"
    )


def test_fr13_audio_reminder_exactly_60_seconds_old_is_missed(fake_stages):
    """FR-13: a reminder exactly 60 s old is "Missed reminder, 1:59 pm: ..."."""
    _audio_ok(
        fake_stages,
        "2026-10-09T13:59:00+05:30",
        "Missed reminder, 1:59 pm: call the lab",
    )


def test_fr13_audio_missed_reminder_an_hour_old(fake_stages):
    """FR-13: a missed reminder from an hour ago is "Missed reminder, 1 pm: ..."."""
    _audio_ok(fake_stages, PAST, "Missed reminder, 1 pm: call the lab")


def test_fr13_audio_missed_reminder_from_another_day(fake_stages):
    """FR-13: a missed reminder from another day includes the date:
    "Missed reminder, 8 October, 5 pm: ..."."""
    _audio_ok(
        fake_stages,
        "2026-10-08T17:00:00+05:30",
        "Missed reminder, 8 October, 5 pm: call the lab",
    )


def test_fr13_audio_fetch_keeps_status_pending(fake_stages):
    """FR-13: fetching the audio never changes status; only ack marks delivered.
    The reminder stays pending and due after one and after two fetches."""
    rid = _add("call the lab", PAST)
    for _ in range(2):
        assert client.get(f"/reminders/{rid}/audio").status_code == 200
        assert rid in _pending_ids()
        due = client.get("/reminders/due")
        assert due.status_code == 200
        assert [r["id"] for r in due.json()] == [rid]


def test_fr13_audio_unknown_id_returns_404(fake_stages):
    """FR-13: an unknown id gives 404 {"error": "reminder not found"} and TTS
    is not called."""
    response = client.get("/reminders/999/audio")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert fake_stages["tts"] == []


@pytest.mark.parametrize(
    "bad_id",
    ["abc", "1.5", "-1", "1_0", "%20", "%D9%A3", "1" + "0" * 30, "9" * 5000],
    ids=[
        "letters",
        "decimal",
        "negative",
        "underscore",
        "space",
        "arabic-digit",
        "huge",
        "over-4300-digits",
    ],
)
def test_fr13_audio_non_integer_id_returns_404(fake_stages, bad_id):
    """FR-13: a non-integer or out-of-range id gives 404
    {"error": "reminder not found"}, never 422 or 500, and TTS is not called."""
    rid = _add("keep me", PAST)
    response = client.get(f"/reminders/{bad_id}/audio")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert fake_stages["tts"] == []
    assert _pending_ids() == [rid]


def test_fr13_audio_writes_no_log_line(fake_stages, log_path):
    """FR-13: the audio endpoint (200 and 404) writes no JSONL line."""
    rid = _add("a", PAST)
    assert client.get(f"/reminders/{rid}/audio").status_code == 200
    assert client.get("/reminders/999/audio").status_code == 404
    assert _log_lines(log_path) == []


def test_fr13_audio_handler_is_plain_def():
    """FR-13: GET /reminders/{reminder_id}/audio is a plain def so sqlite and
    Piper run in the thread pool."""
    routes = [
        r
        for r in app.routes
        if getattr(r, "path", None) == "/reminders/{reminder_id}/audio"
        and "GET" in getattr(r, "methods", set())
    ]
    assert len(routes) == 1
    assert not inspect.iscoroutinefunction(routes[0].endpoint)


def _image_bytes(fmt: str) -> bytes:
    """Tiny valid image in the given PIL format, built in code."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (10, 10), (200, 30, 30)).save(buf, format=fmt)
    return buf.getvalue()


def _gif_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("P", (10, 10)).save(buf, format="GIF")
    return buf.getvalue()


def _post_with_image(silent_wav, data: bytes, name="s.jpg", mime="image/jpeg"):
    return client.post(
        "/query",
        files={
            "audio": ("q.wav", silent_wav, "audio/wav"),
            "image": (name, data, mime),
        },
    )


def _assert_image_rejected(response, error, calls):
    assert response.status_code == 400
    assert response.json() == {"error": error}
    assert calls["order"] == []
    assert calls["stt"] == [] and calls["llm"] == [] and calls["tts"] == []


def test_fr20_valid_jpeg_returns_200_and_runs_stages(fake_stages, silent_wav):
    """FR-20: a valid JPEG in the optional `image` field -> 200 audio, all stages run."""
    response = _post_with_image(silent_wav, _image_bytes("JPEG"))
    assert response.status_code == 200
    assert response.content == FAKE_TTS_WAV
    assert fake_stages["order"] == ["stt", "llm", "tts"]


def test_fr20_valid_png_returns_200_and_runs_stages(fake_stages, silent_wav):
    """FR-20: a valid PNG in the `image` field -> 200 audio, all stages run."""
    response = _post_with_image(silent_wav, _image_bytes("PNG"), "s.png", "image/png")
    assert response.status_code == 200
    assert response.content == FAKE_TTS_WAV
    assert fake_stages["order"] == ["stt", "llm", "tts"]


def test_fr20_no_image_works_as_before(fake_stages, silent_wav):
    """FR-20: without an `image` field /query returns 200 as before."""
    response = _post_query(silent_wav)
    assert response.status_code == 200
    assert response.content == FAKE_TTS_WAV
    assert fake_stages["order"] == ["stt", "llm", "tts"]


def test_fr20_default_image_limit_is_two_million_bytes():
    """FR-20: config.IMAGE_MAX_BYTES is 2_000_000."""
    assert config.IMAGE_MAX_BYTES == 2_000_000


def test_fr20_image_over_limit_returns_400_too_large(
    fake_stages, silent_wav, monkeypatch
):
    """FR-20: image over config.IMAGE_MAX_BYTES -> 400 {"error": "image too large"},
    no stage runs."""
    data = _image_bytes("JPEG")
    monkeypatch.setattr(config, "IMAGE_MAX_BYTES", 100)
    assert len(data) > 100
    response = _post_with_image(silent_wav, data)
    _assert_image_rejected(response, "image too large", fake_stages)


def test_fr20_image_one_byte_over_limit_returns_400(
    fake_stages, silent_wav, monkeypatch
):
    """FR-20: an image of IMAGE_MAX_BYTES + 1 bytes -> 400 "image too large"."""
    data = _image_bytes("JPEG")
    monkeypatch.setattr(config, "IMAGE_MAX_BYTES", len(data) - 1)
    response = _post_with_image(silent_wav, data)
    _assert_image_rejected(response, "image too large", fake_stages)


def test_fr20_image_exactly_at_limit_is_accepted(fake_stages, silent_wav, monkeypatch):
    """FR-20: an image of exactly IMAGE_MAX_BYTES bytes is not too large -> 200."""
    data = _image_bytes("JPEG")
    monkeypatch.setattr(config, "IMAGE_MAX_BYTES", len(data))
    response = _post_with_image(silent_wav, data)
    assert response.status_code == 200
    assert fake_stages["order"] == ["stt", "llm", "tts"]


@pytest.mark.parametrize(
    "data",
    [
        b"not an image",
        _gif_bytes(),
        b"",
        _image_bytes("JPEG")[: len(_image_bytes("JPEG")) // 2],
    ],
    ids=["text", "gif", "empty", "truncated-jpeg"],
)
def test_fr20_unreadable_image_returns_400(fake_stages, silent_wav, data):
    """FR-20: non-image bytes, a GIF, an empty field or a truncated JPEG ->
    400 {"error": "image is not a readable image"}, no stage runs."""
    response = _post_with_image(silent_wav, data)
    _assert_image_rejected(response, "image is not a readable image", fake_stages)


def test_fr20_bad_image_with_valid_audio_skips_stt(fake_stages, silent_wav):
    """FR-20: image checks run before any stage: bad image + valid audio -> no
    stt call."""
    response = _post_with_image(silent_wav, b"not an image")
    assert response.status_code == 400
    assert response.json() == {"error": "image is not a readable image"}
    assert fake_stages["stt"] == []


def test_fr17_image_unreadable_400_writes_one_line(fake_stages, silent_wav, log_path):
    """FR-17/FR-20: a rejected image writes exactly one log line with that error."""
    _post_with_image(silent_wav, b"not an image")
    lines = _log_lines(log_path)
    assert len(lines) == 1
    assert lines[0]["error"] == "image is not a readable image"
    assert lines[0]["answer"] is None
    assert lines[0]["image_sent"] is False


def test_fr17_image_too_large_400_writes_one_line(
    fake_stages, silent_wav, log_path, monkeypatch
):
    """FR-17/FR-20: an oversized image writes exactly one log line with the error."""
    monkeypatch.setattr(config, "IMAGE_MAX_BYTES", 100)
    _post_with_image(silent_wav, _image_bytes("JPEG"))
    lines = _log_lines(log_path)
    assert len(lines) == 1
    assert lines[0]["error"] == "image too large"
    assert lines[0]["image_sent"] is False


def _colored_jpeg(color: tuple[int, int, int]) -> bytes:
    """A valid JPEG whose bytes differ from other colors."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, format="JPEG")
    return buf.getvalue()


IMG_A = _colored_jpeg((250, 10, 10))
IMG_B = _colored_jpeg((10, 10, 250))


def test_fr20_jpeg_upload_reaches_llm_with_mime(fake_stages, silent_wav):
    """FR-20: a JPEG upload reaches llm.ask as (exact bytes, "image/jpeg")."""
    assert _post_with_image(silent_wav, IMG_A).status_code == 200
    assert fake_stages["llm_images"] == [(IMG_A, "image/jpeg")]


def test_fr20_png_upload_reaches_llm_with_mime(fake_stages, silent_wav):
    """FR-20: a PNG upload reaches llm.ask as (exact bytes, "image/png")."""
    png = _image_bytes("PNG")
    response = _post_with_image(silent_wav, png, "s.png", "image/png")
    assert response.status_code == 200
    assert fake_stages["llm_images"] == [(png, "image/png")]


def test_fr20_mime_comes_from_content_not_declared_type(fake_stages, silent_wav):
    """FR-20: the MIME type follows the real format: PNG bytes labelled
    image/jpeg are sent as image/png."""
    png = _image_bytes("PNG")
    response = _post_with_image(silent_wav, png, "s.jpg", "image/jpeg")
    assert response.status_code == 200
    assert fake_stages["llm_images"] == [(png, "image/png")]


def test_fr20_no_image_and_no_session_sends_none(fake_stages, silent_wav):
    """FR-20: with no image and no saved image, llm.ask gets image None."""
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["llm_images"] == [None]


def test_fr21_followup_within_120s_gets_saved_image(fake_stages, silent_wav, clock):
    """FR-21: a text-only query within 120 s of an image query gets the saved
    image."""
    _post_with_image(silent_wav, IMG_A)
    clock.at(60)
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["llm_images"][1] == (IMG_A, "image/jpeg")


def test_fr21_followup_after_121s_gets_no_image(fake_stages, silent_wav, clock):
    """FR-21: a text-only query 121 s after the image query gets image None."""
    _post_with_image(silent_wav, IMG_A)
    clock.at(121)
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["llm_images"][1] is None


def test_fr21_newer_image_replaces_saved_image(fake_stages, silent_wav, clock):
    """FR-21: a new image is sent instead of the saved one and replaces it for
    the next follow-up."""
    _post_with_image(silent_wav, IMG_A)
    clock.at(10)
    _post_with_image(silent_wav, IMG_B)
    clock.at(20)
    _post_query(silent_wav)
    assert fake_stages["llm_images"] == [
        (IMG_A, "image/jpeg"),
        (IMG_B, "image/jpeg"),
        (IMG_B, "image/jpeg"),
    ]


def test_fr21_text_query_keeps_saved_image_for_later(fake_stages, silent_wav, clock):
    """FR-21: a text-only query does not drop the saved image: a second
    follow-up still gets it."""
    _post_with_image(silent_wav, IMG_A)
    clock.at(30)
    _post_query(silent_wav)
    clock.at(60)
    _post_query(silent_wav)
    assert fake_stages["llm_images"][2] == (IMG_A, "image/jpeg")


@pytest.mark.parametrize("stage", ["llm", "tts"])
def test_fr21_failed_image_query_is_not_saved(
    fake_stages, silent_wav, monkeypatch, clock, stage
):
    """FR-21: an image saved only after a 200: a 500 image query leaves nothing
    saved, so the next text-only query gets None."""
    normal = _make_stage_raise(monkeypatch, fake_stages, stage, RuntimeError("boom"))
    clock.at(10)
    assert _post_with_image(silent_wav, IMG_A).status_code == 500
    monkeypatch.setattr(STAGE_FAKES[stage], normal)
    clock.at(20)
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["llm_images"][-1] is None


@pytest.mark.parametrize("stage", ["llm", "tts"])
def test_fr21_failed_image_query_keeps_older_saved_image(
    fake_stages, silent_wav, monkeypatch, clock, stage
):
    """FR-21: a failed image query does not replace the older saved image."""
    _post_with_image(silent_wav, IMG_A)
    normal = _make_stage_raise(monkeypatch, fake_stages, stage, RuntimeError("boom"))
    clock.at(30)
    assert _post_with_image(silent_wav, IMG_B).status_code == 500
    monkeypatch.setattr(STAGE_FAKES[stage], normal)
    clock.at(60)
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["llm_images"][-1] == (IMG_A, "image/jpeg")


def test_fr21_rejected_image_is_not_saved(fake_stages, silent_wav, clock):
    """FR-21: an image rejected with a 400 is not saved: the next text query
    gets None."""
    assert _post_with_image(silent_wav, b"not an image").status_code == 400
    clock.at(10)
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["llm_images"] == [None]


def test_fr22_reset_clears_saved_image(fake_stages, silent_wav, clock):
    """FR-22 / FR-21: POST /session/reset clears the saved image: the next text
    query within 120 s gets None."""
    _post_with_image(silent_wav, IMG_A)
    clock.at(30)
    assert client.post("/session/reset").status_code == 200
    clock.at(60)
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["llm_images"][-1] is None


def test_fr17_image_sent_true_only_for_new_image(
    fake_stages, silent_wav, log_path, clock
):
    """FR-17: image_sent is true for a request that carried an image, false for
    a text follow-up that reused the saved image, false with no image."""
    _post_with_image(silent_wav, IMG_A)
    clock.at(30)
    _post_query(silent_wav)
    clock.at(500)
    _post_query(silent_wav)
    lines = _log_lines(log_path)
    assert [line["image_sent"] for line in lines] == [True, False, False]
    assert fake_stages["llm_images"][1] == (IMG_A, "image/jpeg")


def test_fr17_failed_image_query_logs_image_sent_true(
    fake_stages, silent_wav, monkeypatch, log_path
):
    """FR-17: a 500 whose request carried a valid image logs image_sent true."""
    _make_stage_raise(monkeypatch, fake_stages, "llm", RuntimeError("boom"))
    assert _post_with_image(silent_wav, IMG_A).status_code == 500
    assert _log_lines(log_path)[0]["image_sent"] is True


def test_fr17_log_never_contains_the_image(fake_stages, silent_wav, log_path):
    """FR-17: the log line never holds the image: no bytes, hex or base64 of it,
    and the only image field is the boolean image_sent."""
    import base64

    _post_with_image(silent_wav, IMG_A)
    raw = log_path.read_text(encoding="utf-8")
    assert base64.b64encode(IMG_A[:60]).decode() not in raw
    assert base64.b64encode(IMG_A).decode()[:80] not in raw
    assert IMG_A[:60].hex() not in raw
    assert repr(IMG_A[:40])[2:-1] not in raw
    (line,) = _log_lines(log_path)
    image_keys = [k for k in line if "image" in k.lower()]
    assert image_keys == ["image_sent"]
    assert line["image_sent"] is True


def _lora_call(status: str = "ok") -> dict:
    return {
        "name": "log_concept",
        "args": {"name": "LoRA", "summary": "Low-rank adapters for fine-tuning."},
        "status": status,
    }


def _fake_llm_tool_calls(monkeypatch, calls: list[dict]) -> None:
    monkeypatch.setattr(
        "server.llm.ask",
        lambda question, now, turns=(), image=None: (FAKE_ANSWER, False, calls),
    )


def test_fr17_concept_logged_from_ok_log_concept_call(
    fake_stages, silent_wav, monkeypatch, log_path
):
    """FR-17: the line's concept is the name from an ok log_concept call."""
    _fake_llm_tool_calls(monkeypatch, [_lora_call("ok")])
    assert _post_query(silent_wav).status_code == 200
    (line,) = _log_lines(log_path)
    assert line["concept"] == "LoRA"


def test_fr17_concept_null_without_tool_calls(fake_stages, silent_wav, log_path):
    """FR-17: with no tool calls the line has concept null."""
    assert _post_query(silent_wav).status_code == 200
    (line,) = _log_lines(log_path)
    assert "concept" in line
    assert line["concept"] is None


def test_fr17_concept_null_when_log_concept_failed(
    fake_stages, silent_wav, monkeypatch, log_path
):
    """FR-17: a log_concept call with status failed leaves concept null."""
    _fake_llm_tool_calls(monkeypatch, [_lora_call("failed")])
    assert _post_query(silent_wav).status_code == 200
    (line,) = _log_lines(log_path)
    assert line["concept"] is None


def test_fr17_concept_null_when_only_other_tools_ran(
    fake_stages, silent_wav, monkeypatch, log_path
):
    """FR-17: other tools (add_note ok) do not set concept; it stays null."""
    other = {"name": "add_note", "args": {"text": "buy milk"}, "status": "ok"}
    _fake_llm_tool_calls(monkeypatch, [other])
    assert _post_query(silent_wav).status_code == 200
    (line,) = _log_lines(log_path)
    assert line["concept"] is None


def test_fr17_concept_null_on_audio_400(fake_stages, log_path):
    """FR-17: a failed query (400 bad audio) still has a concept key, null."""
    response = client.post("/query")
    assert response.status_code == 400
    (line,) = _log_lines(log_path)
    assert "concept" in line
    assert line["concept"] is None


def test_fr17_concept_kept_when_llm_fails_after_ok_log_concept(
    fake_stages, silent_wav, monkeypatch, log_path
):
    """FR-17: when llm raises with an ok log_concept in exc.tool_calls, the
    failed query's line still records the concept (it was stored before the failure)."""
    exc = RuntimeError("deadline exceeded")
    exc.tool_calls = [_lora_call("ok")]
    _make_stage_raise(monkeypatch, fake_stages, "llm", exc)
    response = _post_query(silent_wav)
    assert response.status_code == 500
    assert response.json() == {"error": "llm: deadline exceeded"}
    (line,) = _log_lines(log_path)
    assert line["concept"] == "LoRA"


# --- quiz answers (FR-24, FR-17) ---


def _start_quiz(*names: str) -> None:
    """Log the concepts (oldest first) and start a quiz at FIXED_NOW."""
    from server import store, tools

    for day, name in enumerate(names, start=1):
        store.log_concept(name, f"summary of {name}", f"2026-10-0{day}T10:00:00+05:30")
    out = tools.run("start_quiz", {}, FIXED_NOW)
    assert out["count"] == len(names)


def _concept_row(db_path, name: str) -> tuple:
    import sqlite3

    con = sqlite3.connect(db_path)
    try:
        return con.execute(
            "SELECT status, last_quizzed FROM concepts WHERE name = ?", (name,)
        ).fetchone()
    finally:
        con.close()


def test_fr24_quiz_answer_is_graded_and_ask_not_called(fake_stages, silent_wav):
    """FR-24: during a quiz the transcript is graded for the current concept
    with llm.grade(name, summary, transcript); llm.ask is not called."""
    _start_quiz("LoRA", "Attention")
    fake_stages["transcript"] = "low rank adapters"
    response = _post_query(silent_wav)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == FAKE_TTS_WAV
    assert fake_stages["order"] == ["stt", "grade", "tts"]
    assert fake_stages["llm"] == []
    assert fake_stages["grade"] == [("LoRA", "summary of LoRA", "low rank adapters")]


def test_fr24_question_like_answer_is_still_graded(fake_stages, silent_wav):
    """FR-24: a transcript that sounds like a question is still graded as the
    answer while a quiz is running."""
    _start_quiz("LoRA", "Attention")
    fake_stages["transcript"] = "what is LoRA?"
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["llm"] == []
    assert fake_stages["grade"] == [("LoRA", "summary of LoRA", "what is LoRA?")]


def test_fr24_spoken_text_is_feedback_then_next_question(fake_stages, silent_wav):
    """FR-24: TTS speaks the feedback, a space, then the next question
    'Explain <name> in one sentence.'"""
    _start_quiz("LoRA", "Attention")
    fake_stages["grade_result"] = {"correct": True, "feedback": "Yes, well done."}
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["tts"] == ["Yes, well done. Explain Attention in one sentence."]


def test_fr24_next_answer_is_graded_against_next_concept(fake_stages, silent_wav):
    """FR-24: after one answer the quiz advances to the next concept."""
    _start_quiz("LoRA", "Attention")
    assert _post_query(silent_wav).status_code == 200
    fake_stages["transcript"] = "it weights tokens"
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["grade"][1] == (
        "Attention",
        "summary of Attention",
        "it weights tokens",
    )


def test_fr24_last_answer_speaks_score_and_ends_quiz(fake_stages, silent_wav):
    """FR-24: after the last concept TTS speaks the feedback and '<right> of
    <total> right', and the quiz is over (a later query goes to llm.ask)."""
    from server import session

    _start_quiz("LoRA", "Attention")
    fake_stages["grade_result"] = {"correct": True, "feedback": "Right."}
    assert _post_query(silent_wav).status_code == 200
    fake_stages["grade_result"] = {"correct": False, "feedback": "Not quite."}
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["tts"][-1] == "Not quite. 1 of 2 right"
    assert session.quiz(FIXED_NOW) is None
    assert _post_query(silent_wav).status_code == 200
    assert len(fake_stages["llm"]) == 1
    assert len(fake_stages["grade"]) == 2


def test_fr24_graded_answers_set_status_and_last_quizzed(fake_stages, silent_wav, db):
    """FR-24: grading saves the concept's status (right or wrong) and sets
    last_quizzed to now."""
    _start_quiz("LoRA", "Attention")
    fake_stages["grade_result"] = {"correct": True, "feedback": "Right."}
    assert _post_query(silent_wav).status_code == 200
    fake_stages["grade_result"] = {"correct": False, "feedback": "No."}
    assert _post_query(silent_wav).status_code == 200
    assert _concept_row(db, "LoRA") == ("right", FIXED_NOW.isoformat())
    assert _concept_row(db, "Attention") == ("wrong", FIXED_NOW.isoformat())


def test_fr24_grading_failure_returns_500_and_quiz_stays(fake_stages, silent_wav, db):
    """FR-24: if grading fails the response is 500 {"error": "llm: boom"}, the
    quiz stays on the same question and the store row is unchanged."""
    from server import session

    _start_quiz("LoRA", "Attention")
    before = _concept_row(db, "LoRA")
    fake_stages["grade_result"] = RuntimeError("boom")
    response = _post_query(silent_wav)
    assert response.status_code == 500
    assert response.json() == {"error": "llm: boom"}
    assert fake_stages["order"] == ["stt", "grade"]
    state = session.quiz(FIXED_NOW)
    assert state["index"] == 0
    assert state["right"] == 0
    assert _concept_row(db, "LoRA") == before
    assert _concept_row(db, "LoRA")[0] == "new"


def test_fr24_tts_failure_keeps_quiz_on_same_question(
    fake_stages, silent_wav, db, monkeypatch
):
    """FR-24: if speaking the grade fails the quiz stays on the same question and the
    store row is unchanged, so the user is asked again."""
    from server import session

    def fail(text):
        raise RuntimeError("no voice")

    _start_quiz("LoRA", "Attention")
    monkeypatch.setattr("server.tts.synthesize", fail)
    response = _post_query(silent_wav)
    assert response.status_code == 500
    assert response.json() == {"error": "tts: no voice"}
    assert session.quiz(FIXED_NOW)["index"] == 0
    assert _concept_row(db, "LoRA")[0] == "new"


def test_fr17_grading_failure_writes_one_line_without_concept(
    fake_stages, silent_wav, log_path
):
    """FR-17: a failed grading query writes one line with the error and no
    concept logged."""
    _start_quiz("LoRA", "Attention")
    fake_stages["grade_result"] = RuntimeError("boom")
    assert _post_query(silent_wav).status_code == 500
    (line,) = _log_lines(log_path)
    assert line["error"] == "llm: boom"
    assert line["concept"] is None


def test_fr17_quiz_query_writes_one_line_with_transcript_and_spoken_answer(
    fake_stages, silent_wav, log_path
):
    """FR-17: a quiz query writes one line: question = transcript, answer =
    spoken text, error null, tool_calls [], timings for stt, llm and tts."""
    _start_quiz("LoRA", "Attention")
    fake_stages["transcript"] = "low rank adapters"
    fake_stages["grade_result"] = {"correct": True, "feedback": "Right."}
    assert _post_query(silent_wav).status_code == 200
    (line,) = _log_lines(log_path)
    assert line["question"] == "low rank adapters"
    assert line["answer"] == "Right. Explain Attention in one sentence."
    assert line["error"] is None
    assert line["tool_calls"] == []
    assert {"stt", "llm", "tts"} <= set(line["timings_ms"])


def test_fr24_without_quiz_query_still_calls_ask(fake_stages, silent_wav):
    """FR-24: with no running quiz /query runs stt, llm.ask, tts as before and
    never grades."""
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["order"] == ["stt", "llm", "tts"]
    assert fake_stages["grade"] == []


# --- quiz stop, expiry and reset (FR-24, FR-22) ---

STOPPED = "Quiz stopped."


def test_fr24_stop_phrase_default_is_stop_quiz():
    """FR-24: config.QUIZ_STOP_PHRASE is 'stop quiz'."""
    assert config.QUIZ_STOP_PHRASE == "stop quiz"


@pytest.mark.parametrize(
    "transcript",
    ["stop quiz", "Stop quiz.", "okay, STOP quiz!"],
    ids=["plain", "punctuated", "embedded"],
)
def test_fr24_stop_phrase_ends_quiz_without_llm(fake_stages, silent_wav, transcript):
    """FR-24: while a quiz runs, a transcript containing 'stop quiz' (lowercased,
    punctuation removed) ends it: 200 audio/wav speaking exactly 'Quiz stopped.',
    stages stt then tts, no ask and no grade, and the quiz is over."""
    from server import session

    _start_quiz("LoRA", "Attention")
    fake_stages["transcript"] = transcript
    response = _post_query(silent_wav)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == FAKE_TTS_WAV
    assert fake_stages["order"] == ["stt", "tts"]
    assert fake_stages["tts"] == [STOPPED]
    assert fake_stages["llm"] == []
    assert fake_stages["grade"] == []
    assert session.quiz(FIXED_NOW) is None


def test_fr24_stop_keeps_graded_statuses(fake_stages, silent_wav, db):
    """FR-24: stopping keeps statuses already graded; the unasked concept stays new."""
    _start_quiz("LoRA", "Attention")
    fake_stages["grade_result"] = {"correct": False, "feedback": "No."}
    assert _post_query(silent_wav).status_code == 200
    fake_stages["transcript"] = "Stop quiz."
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["tts"][-1] == STOPPED
    assert len(fake_stages["grade"]) == 1
    assert _concept_row(db, "LoRA") == ("wrong", FIXED_NOW.isoformat())
    assert _concept_row(db, "Attention")[0] == "new"


def test_fr17_stop_quiz_writes_one_line(fake_stages, silent_wav, log_path):
    """FR-17: stopping a quiz writes one line: question = transcript, answer =
    'Quiz stopped.', error null."""
    _start_quiz("LoRA", "Attention")
    fake_stages["transcript"] = "Stop quiz."
    assert _post_query(silent_wav).status_code == 200
    (line,) = _log_lines(log_path)
    assert line["question"] == "Stop quiz."
    assert line["answer"] == STOPPED
    assert line["error"] is None


def test_fr24_stop_phrase_without_quiz_is_ordinary_question(fake_stages, silent_wav):
    """FR-24: with no running quiz 'stop quiz' goes to llm.ask like any question."""
    fake_stages["transcript"] = "stop quiz"
    response = _post_query(silent_wav)
    assert response.status_code == 200
    assert fake_stages["order"] == ["stt", "llm", "tts"]
    assert fake_stages["llm"][0][0] == "stop quiz"
    assert fake_stages["tts"] == [FAKE_ANSWER]


def test_fr24_session_expiry_does_not_end_quiz(fake_stages, silent_wav, clock):
    """FR-24: the 120 s session expiry does not end a quiz: a query 200 s after
    the start is still graded."""
    _start_quiz("LoRA", "Attention")
    clock.at(200)
    fake_stages["transcript"] = "low rank adapters"
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["grade"] == [("LoRA", "summary of LoRA", "low rank adapters")]
    assert fake_stages["llm"] == []


def test_fr24_answer_wait_300s_ends_quiz_quietly(fake_stages, silent_wav, clock, db):
    """FR-24: 300 s (QUIZ_ANSWER_WAIT_S) without an answer ends the quiz quietly:
    the query is an ordinary question, the quiz is None, and the concept's status
    and last_quizzed are unchanged."""
    from server import session

    assert config.QUIZ_ANSWER_WAIT_S == 300
    _start_quiz("LoRA", "Attention")
    before = _concept_row(db, "LoRA")
    clock.at(300)
    response = _post_query(silent_wav)
    assert response.status_code == 200
    assert fake_stages["order"] == ["stt", "llm", "tts"]
    assert fake_stages["grade"] == []
    assert session.quiz(clock.t) is None
    assert _concept_row(db, "LoRA") == before


def test_fr22_reset_clears_running_quiz(fake_stages, silent_wav):
    """FR-22: POST /session/reset returns 200 {"status": "ok"} and clears a
    running quiz: the next query goes to llm.ask, not grade."""
    from server import session

    _start_quiz("LoRA", "Attention")
    response = client.post("/session/reset")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert session.quiz(FIXED_NOW) is None
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["order"] == ["stt", "llm", "tts"]
    assert fake_stages["grade"] == []


# --- wipe memories: request and confirmation (FR-35) ---

WIPE_REQUEST = "wipe my memories"
WIPE_CONFIRM = "yes wipe everything"


def _store_memories(n: int) -> None:
    from server import store

    for i in range(n):
        store.add_memory(f"fact number {i}", store.FACT, "2026-10-09T10:00:00+05:30")


def _say(fake_stages, silent_wav, transcript: str):
    fake_stages["transcript"] = transcript
    return _post_query(silent_wav)


def _request_wipe(fake_stages, silent_wav) -> None:
    assert _say(fake_stages, silent_wav, WIPE_REQUEST).status_code == 200


def _other_rows() -> tuple:
    from server import store

    store.add_note("buy milk", "2026-10-09T10:00:00+05:30")
    store.add_reminder(
        "call mom", "2026-10-09T18:00:00+05:30", "2026-10-09T10:00:00+05:30"
    )
    store.log_concept("LoRA", "low rank adapters", "2026-10-09T10:00:00+05:30")
    return _snapshot_other_rows()


def _snapshot_other_rows() -> tuple:
    from server import store

    return (store.list_notes(), store.list_pending(), store.concept_names())


def test_fr35_wipe_phrases_default_in_config():
    """FR-35: config.WIPE_REQUEST_PHRASE is 'wipe my memories' and
    config.WIPE_CONFIRM_PHRASE is 'yes wipe everything'."""
    assert config.WIPE_REQUEST_PHRASE == WIPE_REQUEST
    assert config.WIPE_CONFIRM_PHRASE == WIPE_CONFIRM


def test_fr35_request_asks_back_for_the_confirmation_phrase(fake_stages, silent_wav):
    """FR-35: 'wipe my memories' answers 200 audio/wav with a spoken text that
    contains the confirmation phrase."""
    response = _say(fake_stages, silent_wav, "Wipe my memories.")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == FAKE_TTS_WAV
    assert fake_stages["order"] == ["stt", "tts"]
    assert WIPE_CONFIRM in fake_stages["tts"][0].lower()


def test_fr35_request_deletes_nothing(fake_stages, silent_wav):
    """FR-35: the request turn deletes no memory."""
    from server import store

    _store_memories(8)
    _request_wipe(fake_stages, silent_wav)
    assert store.count_memories() == 8


def test_fr35_request_leaves_the_wipe_pending(fake_stages, silent_wav):
    """FR-35: after the request turn the wipe is pending at the query time."""
    from server import session

    _request_wipe(fake_stages, silent_wav)
    assert session.pending_wipe(FIXED_NOW) is True


def test_fr35_request_does_not_call_ask(fake_stages, silent_wav):
    """FR-35: Gemini (llm.ask) is not called on the request turn."""
    _request_wipe(fake_stages, silent_wav)
    assert fake_stages["llm"] == []
    assert fake_stages["grade"] == []


def test_fr35_request_phrase_embedded_also_asks_back(fake_stages, silent_wav):
    """FR-35: a transcript that contains the request phrase ('Please wipe my
    memories') also asks back and deletes nothing."""
    from server import session, store

    _store_memories(3)
    response = _say(fake_stages, silent_wav, "Please, wipe my memories!")
    assert response.status_code == 200
    assert fake_stages["llm"] == []
    assert WIPE_CONFIRM in fake_stages["tts"][0].lower()
    assert session.pending_wipe(FIXED_NOW) is True
    assert store.count_memories() == 3


def test_fr35_request_adds_no_session_turn(fake_stages, silent_wav):
    """FR-35: the request turn adds no turn to the session."""
    from server import session

    _request_wipe(fake_stages, silent_wav)
    assert session.turns(FIXED_NOW) == []


@pytest.mark.parametrize(
    "transcript",
    ["Yes wipe everything.", "YES WIPE EVERYTHING", "Yes, wipe everything!"],
    ids=["period", "upper", "comma-bang"],
)
def test_fr35_exact_phrase_wipes_every_memory_and_says_how_many(
    fake_stages, silent_wav, transcript
):
    """FR-35: the exact confirmation phrase (ignoring case and punctuation)
    wipes every memory and says how many were wiped."""
    from server import session, store

    _store_memories(8)
    _request_wipe(fake_stages, silent_wav)
    response = _say(fake_stages, silent_wav, transcript)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == FAKE_TTS_WAV
    assert fake_stages["tts"][-1] == "Wiped 8 memories."
    assert store.count_memories() == 0
    assert session.pending_wipe(FIXED_NOW) is False
    assert fake_stages["llm"] == []


def test_fr35_confirm_with_one_memory_says_memory_singular(fake_stages, silent_wav):
    """FR-35: exactly one stored memory is announced as 'Wiped 1 memory.'"""
    from server import store

    _store_memories(1)
    _request_wipe(fake_stages, silent_wav)
    _say(fake_stages, silent_wav, WIPE_CONFIRM)
    assert fake_stages["tts"][-1] == "Wiped 1 memory."
    assert store.count_memories() == 0


def test_fr35_confirm_with_no_memories_says_zero(fake_stages, silent_wav):
    """FR-35: with nothing stored the answer is 'Wiped 0 memories.'"""
    _request_wipe(fake_stages, silent_wav)
    _say(fake_stages, silent_wav, WIPE_CONFIRM)
    assert fake_stages["tts"][-1] == "Wiped 0 memories."


def test_fr35_wipe_leaves_notes_reminders_and_concepts(fake_stages, silent_wav):
    """FR-35: a wipe leaves notes, reminders and concepts untouched."""
    _store_memories(4)
    before = _other_rows()
    assert all(before)
    _request_wipe(fake_stages, silent_wav)
    _say(fake_stages, silent_wav, WIPE_CONFIRM)
    assert _snapshot_other_rows() == before


@pytest.mark.parametrize(
    "transcript",
    ["yes wipe it all", "yes wipe everything now", "wipe everything", "yes"],
)
def test_fr35_near_miss_cancels_and_deletes_nothing(
    fake_stages, silent_wav, transcript
):
    """FR-35: anything but the exact phrase deletes nothing, says it was
    cancelled and clears the pending wipe; Gemini is not called."""
    from server import session, store

    _store_memories(5)
    before = _other_rows()
    _request_wipe(fake_stages, silent_wav)
    response = _say(fake_stages, silent_wav, transcript)
    assert response.status_code == 200
    assert response.content == FAKE_TTS_WAV
    assert "cancelled" in fake_stages["tts"][-1].lower()
    assert store.count_memories() == 5
    assert _snapshot_other_rows() == before
    assert session.pending_wipe(FIXED_NOW) is False
    assert fake_stages["llm"] == []


def test_fr35_cancel_gives_no_second_chance(fake_stages, silent_wav):
    """FR-35: after a cancel the old confirmation phrase is an ordinary
    question: it goes to llm.ask and deletes nothing."""
    from server import store

    _store_memories(5)
    _request_wipe(fake_stages, silent_wav)
    _say(fake_stages, silent_wav, "yes wipe it all")
    assert _say(fake_stages, silent_wav, WIPE_CONFIRM).status_code == 200
    assert [q for q, _ in fake_stages["llm"]] == [WIPE_CONFIRM]
    assert fake_stages["tts"][-1] == FAKE_ANSWER
    assert store.count_memories() == 5


def test_fr35_plain_question_after_cancel_goes_to_ask(fake_stages, silent_wav):
    """FR-35: after a cancel a normal question is answered by llm.ask."""
    _request_wipe(fake_stages, silent_wav)
    _say(fake_stages, silent_wav, "no thanks")
    assert _say(fake_stages, silent_wav, "what time is it").status_code == 200
    assert [q for q, _ in fake_stages["llm"]] == ["what time is it"]
    assert fake_stages["tts"][-1] == FAKE_ANSWER


def test_fr35_confirm_phrase_without_request_is_an_ordinary_question(
    fake_stages, silent_wav
):
    """FR-35: the confirmation phrase with no prior request goes to llm.ask
    and deletes nothing."""
    from server import store

    _store_memories(3)
    assert _say(fake_stages, silent_wav, WIPE_CONFIRM).status_code == 200
    assert [q for q, _ in fake_stages["llm"]] == [WIPE_CONFIRM]
    assert fake_stages["tts"][-1] == FAKE_ANSWER
    assert store.count_memories() == 3


def test_fr35_ordinary_question_unchanged_without_wipe_words(fake_stages, silent_wav):
    """FR-35: a normal question still runs stt, llm.ask, tts."""
    assert _post_query(silent_wav).status_code == 200
    assert fake_stages["order"] == ["stt", "llm", "tts"]


def test_fr35_pending_wipe_expires_at_session_ttl(fake_stages, silent_wav, clock):
    """FR-35: at exactly SESSION_TTL_S after the request the wipe has expired:
    the confirmation phrase is an ordinary question and nothing is deleted."""
    from server import store

    _store_memories(3)
    _request_wipe(fake_stages, silent_wav)
    clock.at(config.SESSION_TTL_S)
    assert _say(fake_stages, silent_wav, WIPE_CONFIRM).status_code == 200
    assert [q for q, _ in fake_stages["llm"]] == [WIPE_CONFIRM]
    assert store.count_memories() == 3


def test_fr35_confirm_just_before_ttl_still_wipes(fake_stages, silent_wav, clock):
    """FR-35: one second before SESSION_TTL_S the confirmation still wipes."""
    from server import store

    _store_memories(3)
    _request_wipe(fake_stages, silent_wav)
    clock.at(config.SESSION_TTL_S - 1)
    _say(fake_stages, silent_wav, WIPE_CONFIRM)
    assert fake_stages["tts"][-1] == "Wiped 3 memories."
    assert store.count_memories() == 0


def test_fr35_session_reset_clears_pending_wipe(fake_stages, silent_wav):
    """FR-35: POST /session/reset clears a pending wipe, so the confirmation
    phrase is an ordinary question afterwards."""
    from server import session, store

    _store_memories(3)
    _request_wipe(fake_stages, silent_wav)
    assert client.post("/session/reset").status_code == 200
    assert session.pending_wipe(FIXED_NOW) is False
    _say(fake_stages, silent_wav, WIPE_CONFIRM)
    assert [q for q, _ in fake_stages["llm"]] == [WIPE_CONFIRM]
    assert store.count_memories() == 3


def test_fr35_tts_failure_on_confirm_returns_500_and_wipes_nothing(
    fake_stages, silent_wav, monkeypatch
):
    """FR-35: if speaking the result fails the response is 500
    {"error": "tts: no voice"}, no memory is deleted and the wipe is still
    pending."""
    from server import session, store

    def fail(text):
        raise RuntimeError("no voice")

    _store_memories(4)
    _request_wipe(fake_stages, silent_wav)
    monkeypatch.setattr("server.tts.synthesize", fail)
    response = _say(fake_stages, silent_wav, WIPE_CONFIRM)
    assert response.status_code == 500
    assert response.json() == {"error": "tts: no voice"}
    assert store.count_memories() == 4
    assert session.pending_wipe(FIXED_NOW) is True


def test_fr35_retry_after_tts_failure_wipes(fake_stages, silent_wav, monkeypatch):
    """FR-35: after a failed confirmation turn, repeating the phrase within
    the window wipes everything."""
    from server import store

    def fail(text):
        raise RuntimeError("no voice")

    _store_memories(4)
    _request_wipe(fake_stages, silent_wav)
    working = server.tts.synthesize
    monkeypatch.setattr("server.tts.synthesize", fail)
    assert _say(fake_stages, silent_wav, WIPE_CONFIRM).status_code == 500
    monkeypatch.setattr("server.tts.synthesize", working)
    assert _say(fake_stages, silent_wav, WIPE_CONFIRM).status_code == 200
    assert fake_stages["tts"][-1] == "Wiped 4 memories."
    assert store.count_memories() == 0


def test_fr17_wipe_turns_write_one_clean_line_each(fake_stages, silent_wav, log_path):
    """FR-17: the request, the confirmation and a cancel each write one line
    with question = transcript, answer = spoken text, timings, error null and
    tool_calls []."""
    _store_memories(2)
    _request_wipe(fake_stages, silent_wav)
    _say(fake_stages, silent_wav, WIPE_CONFIRM)
    _request_wipe(fake_stages, silent_wav)
    _say(fake_stages, silent_wav, "yes wipe it all")
    lines = _log_lines(log_path)
    assert len(lines) == 4
    assert [line["question"] for line in lines] == [
        WIPE_REQUEST,
        WIPE_CONFIRM,
        WIPE_REQUEST,
        "yes wipe it all",
    ]
    assert [line["answer"] for line in lines] == fake_stages["tts"]
    assert lines[1]["answer"] == "Wiped 2 memories."
    for line in lines:
        assert line["error"] is None
        assert line["tool_calls"] == []
        assert {"stt", "tts"} <= set(line["timings_ms"])


# --- memories_used in every /query log line (FR-17, FR-37) ---


def _memory_call(count: int | None, name: str = "search_memories") -> dict:
    call = {"name": name, "args": {"query": "x"}, "status": "ok"}
    if count is not None:
        call["memories"] = count
    return call


def test_fr17_memories_used_sums_counts_of_tool_calls(
    fake_stages, silent_wav, monkeypatch, log_path
):
    """FR-17: memories_used is the sum of the "memories" counts of the tool calls (3 + 2 = 5)."""
    _fake_llm_tool_calls(monkeypatch, [_memory_call(3), _memory_call(2)])
    assert _post_query(silent_wav).status_code == 200
    (line,) = _log_lines(log_path)
    assert line["memories_used"] == 5


def test_fr17_memories_used_zero_without_tool_calls(fake_stages, silent_wav, log_path):
    """FR-17: a query with no tool calls logs memories_used 0."""
    assert _post_query(silent_wav).status_code == 200
    (line,) = _log_lines(log_path)
    assert line["memories_used"] == 0


def test_fr17_memories_used_zero_when_calls_have_no_memories_key(
    fake_stages, silent_wav, monkeypatch, log_path
):
    """FR-17: tool calls without a "memories" key (e.g. add_note, an empty search) log memories_used 0."""
    other = {"name": "add_note", "args": {"text": "buy milk"}, "status": "ok"}
    _fake_llm_tool_calls(monkeypatch, [other, _memory_call(None)])
    assert _post_query(silent_wav).status_code == 200
    (line,) = _log_lines(log_path)
    assert line["memories_used"] == 0


def test_fr17_memories_used_zero_on_audio_400(fake_stages, log_path):
    """FR-17: a 400 for missing audio still logs memories_used 0."""
    assert client.post("/query").status_code == 400
    (line,) = _log_lines(log_path)
    assert line["memories_used"] == 0


def test_fr17_memories_used_logged_on_llm_failure(
    fake_stages, silent_wav, monkeypatch, log_path
):
    """FR-17: a 500 llm failure whose exception carries tool_calls logs their memories count and the error."""
    exc = RuntimeError("deadline exceeded")
    exc.tool_calls = [_memory_call(4)]
    _make_stage_raise(monkeypatch, fake_stages, "llm", exc)
    response = _post_query(silent_wav)
    assert response.status_code == 500
    assert response.json() == {"error": "llm: deadline exceeded"}
    (line,) = _log_lines(log_path)
    assert line["memories_used"] == 4
    assert line["error"] == "llm: deadline exceeded"


def test_fr17_memories_used_zero_on_llm_failure_without_tool_calls(
    fake_stages, silent_wav, monkeypatch, log_path
):
    """FR-17: a 500 llm failure with no tool_calls attribute logs memories_used 0."""
    _make_stage_raise(monkeypatch, fake_stages, "llm", RuntimeError("boom"))
    assert _post_query(silent_wav).status_code == 500
    (line,) = _log_lines(log_path)
    assert line["memories_used"] == 0


def test_fr17_log_line_never_contains_memory_text(
    fake_stages, silent_wav, monkeypatch, log_path
):
    """FR-17: the log line holds only the count of memory items, never any stored memory text."""
    from server import store

    word = "zyxwvutsrq"
    store.add_memory(
        f"I keep a {word} on my desk", store.FACT, "2026-10-09T10:00:00+05:30"
    )
    _fake_llm_tool_calls(monkeypatch, [_memory_call(1)])
    assert _post_query(silent_wav).status_code == 200
    raw = log_path.read_text(encoding="utf-8")
    assert word not in raw
    (line,) = _log_lines(log_path)
    assert line["memories_used"] == 1


def test_fr17_memories_used_is_an_int_in_every_line(
    fake_stages, silent_wav, monkeypatch, log_path
):
    """FR-17: memories_used is an int (not null, not bool) in a success, a 400 and a 500 line."""
    _fake_llm_tool_calls(monkeypatch, [_memory_call(2)])
    _post_query(silent_wav)
    client.post("/query")
    _make_stage_raise(monkeypatch, fake_stages, "llm", RuntimeError("boom"))
    _post_query(silent_wav)
    lines = _log_lines(log_path)
    assert len(lines) == 3
    for line in lines:
        assert type(line["memories_used"]) is int


# --- profile loaded at startup (FR-26, FR-27, FR-28) ---

PROFILE_SCHEMA = [
    {"name": "identity", "description": "who", "question": "Who are you?"},
    {"name": "goal", "description": "aim", "question": "What is your goal?"},
]


def _profile_files(monkeypatch, tmp_path, schema=None, values=None):
    """Point the profile paths at tmp_path and reset module state (restored by monkeypatch).
    schema/values may be a str (written raw), a JSON-able object, or None (values: no file)."""
    from server import profile

    monkeypatch.setattr(profile, "_slots", [])
    monkeypatch.setattr(profile, "_values", {})
    schema_path = tmp_path / "profile_schema.json"
    values_path = tmp_path / "profile.json"
    raw = schema if isinstance(schema, str) else json.dumps(schema or PROFILE_SCHEMA)
    schema_path.write_text(raw, encoding="utf-8")
    if values is not None:
        raw = values if isinstance(values, str) else json.dumps(values)
        values_path.write_text(raw, encoding="utf-8")
    monkeypatch.setattr("server.config.PROFILE_SCHEMA_PATH", schema_path)
    monkeypatch.setattr("server.config.PROFILE_VALUES_PATH", values_path)


def test_fr27_startup_loads_profile_schema_and_values(
    fake_stages, db, monkeypatch, tmp_path
):
    """FR-26/27: entering the lifespan loads the profile schema and values files."""
    from server import profile

    _profile_files(
        monkeypatch,
        tmp_path,
        values={"identity": "second-year engineering student", "goal": ""},
    )
    assert profile.render() == ""
    with TestClient(app):
        assert profile.render() == "identity: second-year engineering student"


def test_fr27_startup_with_missing_values_file_has_empty_profile(
    fake_stages, db, monkeypatch, tmp_path
):
    """FR-27: a missing values file does not stop startup; the profile is empty."""
    from server import profile

    _profile_files(monkeypatch, tmp_path)
    with TestClient(app):
        assert profile.render() == ""


@pytest.mark.parametrize("bad", ["{not json", "[1, 2"], ids=["brace", "bracket"])
def test_fr26_startup_stops_on_malformed_schema(
    fake_stages, db, monkeypatch, tmp_path, bad
):
    """FR-26: a malformed schema file stops startup with ProfileError."""
    from server import profile

    _profile_files(monkeypatch, tmp_path, schema=bad, values={})
    with pytest.raises(profile.ProfileError), TestClient(app):
        pass


def test_fr27_startup_stops_on_malformed_values(fake_stages, db, monkeypatch, tmp_path):
    """FR-27: a malformed values file stops startup with ProfileError."""
    from server import profile

    _profile_files(monkeypatch, tmp_path, values="{not json")
    with pytest.raises(profile.ProfileError), TestClient(app):
        pass


def test_fr28_startup_stops_when_profile_exceeds_line_cap(
    fake_stages, db, monkeypatch, tmp_path
):
    """FR-28: a profile rendering over PROFILE_MAX_LINES stops startup with ProfileError."""
    from server import profile

    _profile_files(monkeypatch, tmp_path, values={"identity": "a", "goal": "b"})
    monkeypatch.setattr("server.config.PROFILE_MAX_LINES", 1)
    with pytest.raises(profile.ProfileError), TestClient(app):
        pass
