import json

import pytest

from server import config, logger


@pytest.fixture
def log_path(tmp_path, monkeypatch):
    path = tmp_path / "queries.jsonl"
    monkeypatch.setattr(config, "LOG_PATH", path)
    return path


def make_record(**overrides):
    record = {
        "question": "what is the weather",
        "answer": "It is sunny.",
        "timings_ms": {"stt": 120, "llm": 900, "tts": 200},
        "searched": True,
        "tool_calls": [{"name": "add_note", "args": {"text": "milk"}, "ok": True}],
        "error": None,
    }
    record.update(overrides)
    return record


def read_lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_fr17_writes_one_line_with_all_fields(log_path):
    """One query writes one JSONL line with time, question, answer, timings,
    searched, tool calls (name, args, ok) and error."""
    record = make_record()
    logger.log_query(dict(record))

    lines = read_lines(log_path)
    assert len(lines) == 1
    line = json.loads(lines[0])
    assert line["time"]
    for key, value in record.items():
        assert line[key] == value


def test_fr17_failed_query_line_keeps_error(log_path):
    """Failed queries are logged too, with their error."""
    logger.log_query(make_record(answer=None, error="stt: boom", timings_ms={"stt": 5}))

    lines = read_lines(log_path)
    assert len(lines) == 1
    line = json.loads(lines[0])
    assert line["error"] == "stt: boom"
    assert line["answer"] is None
    assert line["time"]


def test_fr17_each_query_appends_one_line(log_path):
    """Every query adds exactly one line; earlier lines are kept."""
    logger.log_query(make_record(question="first"))
    logger.log_query(make_record(question="second"))

    lines = read_lines(log_path)
    assert len(lines) == 2
    assert [json.loads(x)["question"] for x in lines] == ["first", "second"]


def test_fr17_api_key_never_in_log(log_path, monkeypatch):
    """No API key or token ever appears in the log."""
    fake_key = "FAKE-KEY-zq81xv7734-do-not-log"
    monkeypatch.setenv("GEMINI_API_KEY", fake_key)

    logger.log_query(make_record())
    logger.log_query(make_record(answer=None, error="llm: failed"))

    assert fake_key not in log_path.read_text(encoding="utf-8")
