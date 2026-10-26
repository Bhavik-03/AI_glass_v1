"""M7-T7: live F9 question list and the last-10 log table (FR-2, FR-15)."""

import json
from pathlib import Path

import pytest

from eval import config as eval_config
from eval import live_log
from eval.run_eval import normalize

LIVE_QUESTIONS = Path(eval_config.ROOT) / "eval" / "live_questions.md"
RECORDED = Path(eval_config.ROOT) / "eval" / "questions.json"


def _live_rows() -> list[list[str]]:
    rows = []
    for line in LIVE_QUESTIONS.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0].isdigit():
            rows.append(cells)
    return rows


def _entry(i: int, **over) -> dict:
    base = {
        "question": f"question {i}",
        "answer": f"answer {i}",
        "timings_ms": {"stt": 1000, "llm": 2000, "tts": 400},
        "error": None,
    }
    return {**base, **over}


def _write_log(path: Path, entries: list[dict], blank: bool = False) -> None:
    lines = []
    for e in entries:
        lines.append(json.dumps(e))
        if blank:
            lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def log_path(tmp_path, monkeypatch):
    path = tmp_path / "queries.jsonl"
    monkeypatch.setattr(eval_config, "LOG_PATH", path)
    return path


def test_fr2_live_questions_has_ten_ordered_rows():
    """10 fixed questions, ids 1..10 in order."""
    rows = _live_rows()
    assert len(rows) == 10
    assert [int(r[0]) for r in rows] == list(range(1, 11))


def test_fr2_live_questions_group_split():
    """4 general, 3 notes, 3 reminders, in that order."""
    groups = [r[1] for r in _live_rows()]
    assert groups == ["general"] * 4 + ["notes"] * 3 + ["reminders"] * 3


def test_fr2_live_questions_texts_filled_and_distinct():
    """Every 'say this' cell is non-empty and the 10 are distinct."""
    texts = [r[2] for r in _live_rows()]
    assert all(texts)
    assert len({normalize(t) for t in texts}) == 10


def test_fr2_live_questions_not_in_recorded_set():
    """None of the 10 equals a spoken text of the 30 recorded questions."""
    recorded = json.loads(RECORDED.read_text(encoding="utf-8"))
    assert len(recorded) == 30
    spoken = {normalize(q["spoken"]) for q in recorded}
    for r in _live_rows():
        assert normalize(r[2]) not in spoken, r[2]


def test_fr15_read_last_returns_last_ten_in_order(log_path):
    """read_last returns only the last 10 of 15 lines, oldest first."""
    _write_log(log_path, [_entry(i) for i in range(1, 16)])
    got = live_log.read_last()
    assert [e["question"] for e in got] == [f"question {i}" for i in range(6, 16)]


def test_fr15_read_last_fewer_than_ten(log_path):
    """Fewer than 10 lines are all returned."""
    _write_log(log_path, [_entry(i) for i in range(1, 4)])
    assert len(live_log.read_last()) == 3


def test_fr15_read_last_absent_file(log_path):
    """An absent log gives an empty list."""
    assert not log_path.exists()
    assert live_log.read_last() == []


def test_fr15_read_last_skips_blank_lines(log_path):
    """Blank lines are skipped and do not count."""
    _write_log(log_path, [_entry(i) for i in range(1, 4)], blank=True)
    got = live_log.read_last()
    assert [e["question"] for e in got] == ["question 1", "question 2", "question 3"]


def test_fr15_latency_sums_stages():
    """latency_s is the total of stt + llm + tts in seconds."""
    assert live_log.latency_s(_entry(1)) == pytest.approx(3.4)


def test_fr15_latency_missing_stage_counts_zero():
    """A stage missing from timings_ms adds nothing."""
    e = _entry(1, timings_ms={"stt": 500, "llm": 1500})
    assert live_log.latency_s(e) == pytest.approx(2.0)


def test_fr15_table_header_rows_and_numbering():
    """Table has the fixed header and one numbered row per entry."""
    lines = live_log.format_table([_entry(1), _entry(2), _entry(3)]).splitlines()
    assert lines[0] == "| # | question | answer | latency s | error |"
    data = [ln for ln in lines if ln.startswith("|")][2:]
    assert len(data) == 3
    for n, ln in enumerate(data, start=1):
        assert ln.split("|")[1].strip() == str(n)


def test_fr15_table_latency_one_decimal():
    """Latency is shown with one decimal."""
    table = live_log.format_table([_entry(1)])
    assert "| 3.4 |" in table


def test_fr15_table_shows_error():
    """A non-empty error appears in the row."""
    table = live_log.format_table([_entry(1, error="llm: boom")])
    assert "llm: boom" in table


def test_fr15_table_multiline_and_pipe_stay_on_one_line():
    """A newline or '|' inside an answer keeps the entry on one line."""
    e = _entry(1, answer="line one\nline two | extra")
    lines = live_log.format_table([e]).splitlines()
    data = [ln for ln in lines if ln.startswith("|")][2:]
    assert len(data) == 1
    assert len(lines) == len([ln for ln in lines if ln.strip()])
    assert data[0].count("|") == 6


def test_fr15_main_prints_table(log_path, capsys):
    """main prints the table of the last log lines."""
    _write_log(log_path, [_entry(1), _entry(2)])
    live_log.main()
    out = capsys.readouterr().out
    assert "| # | question | answer | latency s | error |" in out
    assert "question 2" in out


def test_fr15_main_no_queries_message(log_path, capsys):
    """main prints 'No queries logged yet.' when there are none."""
    live_log.main()
    assert capsys.readouterr().out.strip() == "No queries logged yet."


def _writer_entry(i: int) -> dict:
    return {
        "event": "session_writer",
        "time": f"2026-10-09T14:0{i % 10}:00+05:30",
        "turns": 1,
        "points_returned": 1,
        "rows_added": 1,
        "points_too_long": 0,
        "points_rejected": 0,
        "dropped": [],
        "timings_ms": {"llm": 900},
        "error": None,
    }


def test_fr17_read_last_ignores_session_writer_lines(log_path):
    """FR-17/FR-39: session_writer lines are skipped: read_last returns the last 10 query lines in order and format_table over them works."""
    entries = []
    for i in range(1, 13):
        entries.append(_entry(i))
        if i % 3 == 0:
            entries.append(_writer_entry(i))
    entries.append(_writer_entry(0))
    _write_log(log_path, entries)
    got = live_log.read_last()
    assert [e["question"] for e in got] == [f"question {i}" for i in range(3, 13)]
    assert all("event" not in e for e in got)
    assert live_log.format_table(got)


def test_fr17_only_writer_lines_gives_no_queries(log_path, capsys):
    """FR-17/FR-39: a log of only session_writer lines gives [] and main prints 'No queries logged yet.'."""
    _write_log(log_path, [_writer_entry(1), _writer_entry(2)])
    assert live_log.read_last() == []
    live_log.main()
    assert capsys.readouterr().out.strip() == "No queries logged yet."


def test_fr15_table_handles_failed_query_with_null_fields():
    """A 400 or 500 entry (question and answer null, no timings) still gives one row."""
    entry = {"question": None, "answer": None, "timings_ms": {}, "error": "stt: boom"}
    row = live_log.format_table([entry]).splitlines()[-1]
    assert row == "| 1 |  |  | 0.0 | stt: boom |"
