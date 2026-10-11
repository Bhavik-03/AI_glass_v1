"""Tests for eval/run_eval.py, the eval replay runner (FR-16, FR-17).

Temp DB, fake server (httpx.MockTransport), fake sleep/clock/process list.
No network, models, real sleeping or real PowerShell.
"""

import json
import sqlite3
import subprocess
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from eval import config as eval_config
from eval import run_eval
from server import config as server_config
from server import store

REAL_CLIENT = httpx.Client
CREATED = "2026-10-09T10:00:00+05:30"
DUE = "2026-10-10T10:00:00+05:30"
CLIP_BYTES = b"RIFF-fake-clip-"


def counts(path) -> tuple[int, int]:
    con = sqlite3.connect(path)
    try:
        notes = con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        rems = con.execute("SELECT COUNT(*) FROM reminders").fetchone()[0]
    finally:
        con.close()
    return notes, rems


def questions(n: int = 3) -> list[dict]:
    return [{"id": f"q{i:02d}", "group": "general"} for i in range(1, n + 1)]


@pytest.fixture
def env(db, monkeypatch, tmp_path):
    """Seeded temp DB (2 notes, 1 reminder) plus eval config pointed at tmp_path."""
    store.add_note("buy milk", CREATED)
    store.add_note("call dad", CREATED)
    store.add_reminder("take pills", DUE, CREATED)
    clip_dir = tmp_path / "eval"
    clip_dir.mkdir()
    monkeypatch.setattr(eval_config, "DB_PATH", db)
    monkeypatch.setattr(eval_config, "LOG_PATH", tmp_path / "queries.jsonl")
    monkeypatch.setattr(eval_config, "CLIP_DIR", clip_dir)
    monkeypatch.setattr(eval_config, "MARKER_PATH", clip_dir / "restore-pending")
    monkeypatch.setattr(eval_config, "QUESTIONS_PATH", tmp_path / "questions.json")
    monkeypatch.setattr(eval_config, "SERVER_URL", "http://fake")
    return db


def write_clips(qs: list[dict]) -> None:
    for q in qs:
        (eval_config.CLIP_DIR / f"{q['id']}.wav").write_bytes(
            CLIP_BYTES + q["id"].encode()
        )


def append_log(entry: dict) -> None:
    with eval_config.LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ---------- begin / end (FR-16) ----------


def test_fr16_begin_backs_up_then_clears_rows_keeps_tables(env):
    """begin() backs up the DB, then empties notes and reminders; tables and file stay."""
    run_eval.begin()
    assert env.exists()
    assert counts(env) == (0, 0)
    backups = list(eval_config.CLIP_DIR.glob("backup-*.db"))
    assert len(backups) == 1
    assert counts(backups[0]) == (2, 1)


def test_fr16_marker_holds_backup_path(env):
    """The restore-pending marker holds the path of the backup file."""
    run_eval.begin()
    backup = next(eval_config.CLIP_DIR.glob("backup-*.db"))
    marker = eval_config.MARKER_PATH.read_text(encoding="utf-8").strip()
    assert marker == str(backup)


def test_fr16_end_restores_rows_and_removes_marker(env):
    """end() restores the original rows from the backup and removes the marker."""
    run_eval.begin()
    run_eval.end()
    assert counts(env) == (2, 1)
    assert not eval_config.MARKER_PATH.exists()
    assert len(list(eval_config.CLIP_DIR.glob("backup-*.db"))) == 1


def test_fr16_end_without_marker_does_nothing(env):
    """end() with no marker leaves the DB alone."""
    run_eval.end()
    assert counts(env) == (2, 1)
    assert not eval_config.MARKER_PATH.exists()


def test_fr16_leftover_marker_restored_before_new_backup(env):
    """A marker from a crashed run is restored first, so the new backup holds the user's rows."""
    run_eval.begin()  # simulated crash: no end(); live DB is now empty
    assert counts(env) == (0, 0)
    run_eval.begin()
    backups = list(eval_config.CLIP_DIR.glob("backup-*.db"))
    marker = eval_config.MARKER_PATH.read_text(encoding="utf-8").strip()
    assert counts(marker) == (2, 1)
    assert all(counts(b) == (2, 1) for b in backups)
    assert counts(env) == (0, 0)
    run_eval.end()
    assert counts(env) == (2, 1)


def test_fr16_missing_backup_in_marker_raises_and_changes_nothing(env):
    """A marker naming a missing backup raises RuntimeError and leaves the DB untouched."""
    eval_config.MARKER_PATH.write_text(
        str(eval_config.CLIP_DIR / "backup-gone.db"), encoding="utf-8"
    )
    with pytest.raises(RuntimeError):
        run_eval.begin()
    assert counts(env) == (2, 1)
    assert eval_config.MARKER_PATH.exists()
    assert list(eval_config.CLIP_DIR.glob("backup-*.db")) == []


# ---------- check_clips ----------


def test_fr16_check_clips_lists_missing_ids(env):
    """check_clips returns the ids whose <id>.wav is missing."""
    qs = questions(3)
    write_clips(qs[:2])
    assert run_eval.check_clips(qs) == ["q03"]
    write_clips(qs)
    assert run_eval.check_clips(qs) == []


# ---------- client_running ----------


def fake_run(stdout="", returncode=0, exc=None, seen=None):
    def run(args, **kwargs):
        if seen is not None:
            seen.append((args, kwargs))
        if exc:
            raise exc
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")

    return run


def test_fr16_client_running_true_when_output(env):
    """A PowerShell listing with output means the PC client runs."""
    assert run_eval.client_running(fake_run("1234\n")) is True


def test_fr16_client_running_false_when_blank(env):
    """Blank output means no client process."""
    assert run_eval.client_running(fake_run("  \n")) is False


@pytest.mark.parametrize(
    "run",
    [
        fake_run("1234", returncode=1),
        fake_run(exc=OSError("no powershell")),
        fake_run(exc=subprocess.TimeoutExpired("powershell", 5)),
    ],
    ids=["nonzero", "oserror", "timeout"],
)
def test_fr16_client_running_false_on_failure(env, run):
    """Non-zero exit, OSError or timeout counts as not running."""
    assert run_eval.client_running(run) is False


def test_fr16_client_running_command_names_module(env):
    """The PowerShell command is searched for config.CLIENT_MODULE."""
    seen = []
    run_eval.client_running(fake_run("", seen=seen))
    args, kwargs = seen[0]
    assert "powershell" in str(args[0]).lower()
    assert eval_config.CLIENT_MODULE in " ".join(args)
    assert kwargs.get("capture_output") is True


# ---------- gemini_calls / pace ----------


def test_fr16_gemini_calls_is_tool_calls_plus_one(env):
    """Gemini calls = tool calls + 1; with no log line assume the maximum rounds + 1."""
    assert run_eval.gemini_calls({"tool_calls": []}) == 1
    assert run_eval.gemini_calls({"tool_calls": [{}, {}]}) == 3
    assert run_eval.gemini_calls(None) == server_config.MAX_TOOL_ROUNDS + 1


def test_fr16_pace_sleeps_four_seconds_per_call_minus_elapsed(env):
    """pace sleeps SECONDS_PER_CALL * calls - elapsed."""
    slept = []
    run_eval.pace(1.5, 2, sleep=slept.append)
    assert slept == [pytest.approx(eval_config.SECONDS_PER_CALL * 2 - 1.5)]


def test_fr16_pace_does_not_sleep_when_elapsed_is_longer(env):
    """No sleep call when the query already took longer than its budget."""
    slept = []
    run_eval.pace(30.0, 1, sleep=slept.append)
    assert slept == []


# ---------- log reading (FR-17) ----------


def test_fr17_read_log_since_returns_only_new_lines(env):
    """read_log_since(offset) parses only lines written after the byte offset."""
    append_log({"question": "old"})
    offset = run_eval.log_offset()
    assert offset == eval_config.LOG_PATH.stat().st_size
    append_log({"question": "new1"})
    append_log({"question": "new2"})
    assert [e["question"] for e in run_eval.read_log_since(offset)] == ["new1", "new2"]
    assert run_eval.read_log_since(run_eval.log_offset()) == []


def test_fr17_log_absent_gives_zero_and_empty(env):
    """No log file: offset 0 and no lines."""
    assert run_eval.log_offset() == 0
    assert run_eval.read_log_since(0) == []


# ---------- run_one / replay ----------


class FakeServer:
    """MockTransport handler for /query that also writes the server's log line."""

    def __init__(self, tool_calls=None, status=None, fail=None):
        self.requests: list[httpx.Request] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.tool_calls = tool_calls or {}
        self.status = status or {}  # question index (1-based) -> status code
        self.fail = fail or set()  # indices that raise a connection error

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            self.requests.append(request)
            n = len(self.requests)
            if n in self.fail:
                raise httpx.ConnectError("boom")
            code = self.status.get(n, 200)
            entry = {
                "question": f"asked {n}",
                "answer": "fake answer",
                "searched": False,
                "tool_calls": self.tool_calls.get(n, []),
            }
            if code != 200:
                entry["error"] = "llm: broke"
                append_log(entry)
                return httpx.Response(code, json={"error": "llm: broke"})
            append_log(entry)
            return httpx.Response(
                200, content=b"RIFF-answer", headers={"content-type": "audio/wav"}
            )
        finally:
            self.in_flight -= 1


def make_client(server) -> httpx.Client:
    return REAL_CLIENT(base_url="http://fake", transport=httpx.MockTransport(server))


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        self.t += 1.0
        return self.t


def test_fr17_run_one_posts_audio_field_and_returns_log_line(env):
    """run_one POSTs the clip as multipart field 'audio' to /query and returns status, log line, wall time."""
    qs = questions(1)
    write_clips(qs)
    server = FakeServer(
        tool_calls={1: [{"name": "web_search", "args": {}, "ok": True}]}
    )
    with make_client(server) as client:
        result = run_eval.run_one(
            client, {"id": "q01", "group": "general"}, clock=Clock()
        )
    req = server.requests[0]
    assert req.method == "POST" and req.url.path == "/query"
    assert b'name="audio"' in req.content
    assert CLIP_BYTES + b"q01" in req.content
    assert b"audio/wav" in req.content
    assert result["id"] == "q01" and result["group"] == "general"
    assert result["status"] == 200 and result["error"] is None
    assert result["log"]["question"] == "asked 1"
    assert len(result["log"]["tool_calls"]) == 1
    assert result["wall_s"] > 0


def test_fr16_run_one_records_500_error_text(env):
    """A 500 gives status 500 with the JSON error text and the log line."""
    write_clips(questions(1))
    server = FakeServer(status={1: 500})
    with make_client(server) as client:
        result = run_eval.run_one(
            client, {"id": "q01", "group": "general"}, clock=Clock()
        )
    assert result["status"] == 500
    assert result["error"] == "llm: broke"
    assert result["log"]["error"] == "llm: broke"


def test_fr16_replay_continues_after_500(env):
    """A 500 is recorded and the replay goes on with the next question."""
    qs = questions(3)
    write_clips(qs)
    server = FakeServer(status={2: 500})
    with make_client(server) as client:
        results = run_eval.replay(qs, client, sleep=lambda s: None, clock=Clock())
    assert [r["id"] for r in results] == ["q01", "q02", "q03"]
    assert [r["status"] for r in results] == [200, 500, 200]
    assert len(server.requests) == 3


def test_fr16_replay_records_connection_error_and_continues(env):
    """A connection error gives status None with the exception text; the run continues."""
    qs = questions(3)
    write_clips(qs)
    server = FakeServer(fail={1})
    with make_client(server) as client:
        results = run_eval.replay(qs, client, sleep=lambda s: None, clock=Clock())
    assert results[0]["status"] is None
    assert "boom" in results[0]["error"]
    assert results[0]["log"] is None
    assert [r["status"] for r in results[1:]] == [200, 200]


def test_fr16_replay_in_order_one_at_a_time_with_pacing(env):
    """Clips are posted in order, one request at a time, sleeping 4 s per Gemini call used."""
    qs = questions(3)
    write_clips(qs)
    server = FakeServer(tool_calls={2: [{"name": "a"}, {"name": "b"}]})
    slept = []
    with make_client(server) as client:
        results = run_eval.replay(qs, client, sleep=slept.append, clock=Clock())
    assert server.max_in_flight == 1
    for q, req in zip(qs, server.requests):
        assert CLIP_BYTES + q["id"].encode() in req.content
    per = eval_config.SECONDS_PER_CALL
    calls = [1, 3, 1]
    expected = [per * c - r["wall_s"] for c, r in zip(calls, results)]
    assert slept == [pytest.approx(e) for e in expected]


# ---------- main ----------


@pytest.fixture
def main_env(env, monkeypatch):
    qs = questions(3)
    eval_config.QUESTIONS_PATH.write_text(json.dumps(qs), encoding="utf-8")
    state = {"health": 200, "replayed": 0, "clients": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(state["health"], json={"status": "ok"})
        return httpx.Response(404)

    def factory(*args, **kwargs):
        state["clients"] += 1
        kwargs.pop("transport", None)
        return REAL_CLIENT(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(run_eval.httpx, "Client", factory)
    monkeypatch.setattr(run_eval, "client_running", lambda *a, **k: False)
    write_clips(qs)
    state["env"] = env
    state["qs"] = qs
    return state


def untouched(state) -> bool:
    return (
        counts(state["env"]) == (2, 1)
        and not eval_config.MARKER_PATH.exists()
        and list(eval_config.CLIP_DIR.glob("backup-*.db")) == []
    )


def test_fr16_main_returns_1_when_health_fails(main_env, capsys):
    """main returns 1 with a message and leaves the DB untouched when /health is not 200."""
    main_env["health"] = 503
    assert run_eval.main() == 1
    assert capsys.readouterr().out.strip() != ""
    assert untouched(main_env)


def test_fr16_main_returns_1_when_clips_missing(main_env, capsys):
    """main prints the missing clip ids and returns 1 before touching the DB."""
    (eval_config.CLIP_DIR / "q02.wav").unlink()
    assert run_eval.main() == 1
    assert "q02" in capsys.readouterr().out
    assert untouched(main_env)


def test_fr16_main_restores_db_on_keyboard_interrupt(main_env, monkeypatch):
    """Ctrl+C during the replay still restores the DB and removes the marker."""
    seen = {}

    def boom(qs, client, *a, **k):
        seen["cleared"] = counts(main_env["env"])
        raise KeyboardInterrupt

    monkeypatch.setattr(run_eval, "replay", boom)
    try:
        run_eval.main()
    except KeyboardInterrupt:
        pass
    assert seen["cleared"] == (0, 0)
    assert counts(main_env["env"]) == (2, 1)
    assert not eval_config.MARKER_PATH.exists()


def test_fr16_main_runs_and_restores_on_success(main_env, monkeypatch):
    """A normal run clears the rows for the replay, returns 0 and restores the rows."""
    seen = {}

    def fake_replay(qs, client, *a, **k):
        seen["cleared"] = counts(main_env["env"])
        seen["ids"] = [q["id"] for q in qs]
        return [
            {
                "id": q["id"],
                "group": q["group"],
                "status": 200,
                "error": None,
                "wall_s": 1.0,
                "log": None,
            }
            for q in qs
        ]

    monkeypatch.setattr(run_eval, "replay", fake_replay)
    assert run_eval.main() == 0
    assert seen["cleared"] == (0, 0)
    assert seen["ids"] == ["q01", "q02", "q03"]
    assert counts(main_env["env"]) == (2, 1)
    assert not eval_config.MARKER_PATH.exists()


def test_fr16_main_warns_when_client_running_but_continues(
    main_env, monkeypatch, capsys
):
    """A running PC client prints a warning but does not stop the run."""
    monkeypatch.setattr(run_eval, "client_running", lambda *a, **k: True)
    ran = []
    monkeypatch.setattr(
        run_eval, "replay", lambda qs, client, *a, **k: ran.append(1) or []
    )
    assert run_eval.main() == 0
    assert "warn" in capsys.readouterr().out.lower()
    assert ran == [1]


# ---------- grade (FR-5, FR-8, FR-9, FR-10) ----------

IST = ZoneInfo("Asia/Kolkata")
ASKED = datetime(2026, 10, 11, 9, 30, tzinfo=IST)
TOMORROW_17 = datetime(2026, 10, 12, 17, 0, tzinfo=IST)
EMPTY_DB = {"notes": [], "reminders": []}


def make_result(
    answer="ok",
    searched=False,
    tools=(),
    db=None,
    status=200,
    error=None,
    log="default",
    asked=ASKED,
):
    if log == "default":
        log = {
            "question": "q",
            "answer": answer,
            "searched": searched,
            "tool_calls": [{"name": t, "args": {}, "ok": True} for t in tools],
            "error": None,
            "timings_ms": {"stt": 1, "llm": 2, "tts": 3},
        }
    return {
        "status": status,
        "error": error,
        "log": log,
        "asked_at": asked.isoformat(),
        "db": db or EMPTY_DB,
    }


def rem(text, due, status="pending", id=1):
    return {"id": id, "text": text, "due_at": due.isoformat(), "status": status}


def note(text, id=1):
    return {"id": id, "text": text}


def run_grade(rule, **kw):
    return run_eval.grade(
        {"id": "q", "group": "general", "pass": rule}, make_result(**kw)
    )


def test_fr5_grade_no_pass_key_passes_on_200():
    """A question without a pass rule passes when the status is 200."""
    assert run_eval.grade({"id": "q"}, make_result()) == (True, "ok")


def test_fr5_grade_all_checks_hold_returns_ok():
    """When every check in the rule holds, grade returns (True, 'ok')."""
    rule = {"tools": ["web_search"], "searched": True, "answer_all": [["rain"]]}
    assert run_grade(
        rule, answer="Light rain", searched=True, tools=["web_search"]
    ) == (
        True,
        "ok",
    )


def test_fr5_grade_http_error_fails_with_status_and_error_text():
    """Status != 200 fails; the reason starts with 'http <status>' and has the error text."""
    ok, reason = run_grade(
        {}, status=500, error="llm: broke", log={"question": "q", "error": "llm: broke"}
    )
    assert ok is False
    assert reason.startswith("http 500")
    assert "llm: broke" in reason


def test_fr5_grade_no_log_line_fails():
    """A missing log line (None) fails with 'no log line'."""
    ok, reason = run_grade({"tools": []}, log=None)
    assert ok is False
    assert "no log line" in reason


def test_fr5_grade_no_log_line_fails_even_without_pass_rule():
    """Status 200 with no log line still fails."""
    ok, reason = run_eval.grade({"id": "q"}, make_result(log=None))
    assert ok is False and "no log line" in reason


def test_fr5_grade_tools_all_required_present_passes():
    """Every required tool in tool_calls with ok true passes; extra tools are fine."""
    ok, _ = run_grade({"tools": ["add_note"]}, tools=["list_notes", "add_note"])
    assert ok is True


def test_fr5_grade_tools_empty_list_needs_no_tool():
    """tools == [] passes when no tool was needed."""
    assert run_grade({"tools": []})[0] is True


def test_fr5_grade_tool_missing_fails_naming_tool():
    """A required tool that was not called fails with 'tool add_note not called'."""
    ok, reason = run_grade({"tools": ["add_note"]}, tools=[])
    assert ok is False
    assert "tool add_note not called" in reason


def test_fr5_grade_tool_with_ok_false_fails():
    """A required tool whose logged call has ok false does not count."""
    log = {
        "answer": "done",
        "searched": False,
        "tool_calls": [{"name": "add_note", "args": {}, "ok": False}],
        "error": None,
    }
    ok, reason = run_grade({"tools": ["add_note"]}, log=log)
    assert ok is False
    assert "add_note" in reason


def test_fr8_grade_searched_true_passes_and_false_fails():
    """searched true in the rule needs searched true in the log."""
    assert run_grade({"searched": True}, searched=True)[0] is True
    ok, reason = run_grade({"searched": True}, searched=False)
    assert ok is False
    assert "searched" in reason


def test_fr5_grade_answer_all_each_list_needs_one_alternative():
    """answer_all passes when each alternative-list has one word in the answer."""
    rule = {"answer_all": [["paris", "france"], ["capital"]]}
    assert run_grade(rule, answer="Paris is the capital")[0] is True
    ok, reason = run_grade(rule, answer="Paris is nice")
    assert ok is False
    assert "answer lacks one of" in reason
    assert "capital" in reason


def test_fr5_grade_answer_all_case_insensitive():
    """answer_all matching ignores case."""
    assert run_grade({"answer_all": [["delhi"]]}, answer="It is DELHI.")[0] is True


def test_fr5_grade_answer_all_whole_word_only():
    """'au' must not match 'author'; punctuation still delimits a whole word."""
    rule = {"answer_all": [["au"]]}
    assert run_grade(rule, answer="The author wrote it")[0] is False
    assert run_grade(rule, answer="Symbol au, gold")[0] is True


def test_fr5_grade_answer_some_min_distinct_words():
    """answer_some passes with at least min distinct words found as whole words."""
    rule = {"answer_some": {"min": 2, "words": ["red", "green", "blue"]}}
    assert run_grade(rule, answer="Red and blue")[0] is True
    ok, reason = run_grade(rule, answer="Red red red")
    assert ok is False
    assert "answer_some" in reason


def test_fr5_grade_answer_some_whole_words_only():
    """answer_some does not count a word inside a longer word."""
    rule = {"answer_some": {"min": 1, "words": ["cat"]}}
    assert run_grade(rule, answer="A category")[0] is False
    assert run_grade(rule, answer="A cat")[0] is True


def test_fr8_grade_answer_fact_regex_case_insensitive():
    """answer_fact is a case-insensitive regex search over the answer."""
    rule = {"answer_fact": r"\d+\s*degrees"}
    assert run_grade(rule, answer="It is 31 DEGREES now")[0] is True
    ok, reason = run_grade(rule, answer="It is warm")
    assert ok is False
    assert "answer_fact" in reason


def test_fr9_grade_note_added_all_words_in_one_note():
    """note_added passes when one stored note has all words (case-insensitive substring)."""
    db = {"notes": [note("Buy MILK today", 1)], "reminders": []}
    assert run_grade({"note_added": ["milk", "buy"]}, db=db)[0] is True


def test_fr9_grade_note_added_words_split_across_notes_fails():
    """Words spread over different notes do not count; no notes also fails."""
    db = {"notes": [note("buy bread", 1), note("get milk", 2)], "reminders": []}
    ok, reason = run_grade({"note_added": ["buy", "milk"]}, db=db)
    assert ok is False
    assert "note_added" in reason
    assert run_grade({"note_added": ["milk"]})[0] is False


def test_fr9_grade_notes_total_exact():
    """notes_total needs exactly that many stored notes."""
    db = {"notes": [note("a", 1), note("b", 2)], "reminders": []}
    assert run_grade({"notes_total": 2}, db=db)[0] is True
    ok, reason = run_grade({"notes_total": 3}, db=db)
    assert ok is False
    assert "notes_total" in reason
    assert run_grade({"notes_total": 1}, db=db)[0] is False


def test_fr10_grade_reminder_added_at_tomorrow_exact_passes():
    """reminder_added 'tomorrow 17:00' passes for a matching reminder due tomorrow at 17:00."""
    db = {"notes": [], "reminders": [rem("call the dentist", TOMORROW_17)]}
    rule = {"reminder_added": {"words": ["dentist"], "due": {"at": "tomorrow 17:00"}}}
    assert run_grade(rule, db=db)[0] is True


def test_fr10_grade_reminder_added_at_tolerance_edges():
    """'at' accepts a due_at just inside DUE_AT_TOLERANCE_S and rejects just outside."""
    tol = eval_config.DUE_AT_TOLERANCE_S
    rule = {"reminder_added": {"words": ["dentist"], "due": {"at": "tomorrow 17:00"}}}
    for delta, expected in [
        (tol - 1, True),
        (-(tol - 1), True),
        (tol + 1, False),
        (-(tol + 1), False),
    ]:
        due = TOMORROW_17 + timedelta(seconds=delta)
        db = {"notes": [], "reminders": [rem("dentist", due)]}
        assert run_grade(rule, db=db)[0] is expected, delta


def test_fr10_grade_reminder_added_wrong_day_fails_with_reason():
    """A reminder due today instead of tomorrow fails and names reminder_added."""
    due = datetime(2026, 10, 11, 17, 0, tzinfo=IST)
    db = {"notes": [], "reminders": [rem("dentist", due)]}
    rule = {"reminder_added": {"words": ["dentist"], "due": {"at": "tomorrow 17:00"}}}
    ok, reason = run_grade(rule, db=db)
    assert ok is False
    assert "reminder_added" in reason


def test_fr10_grade_reminder_added_day_after_tomorrow():
    """'day_after_tomorrow 15:00' means asked date + 2 days at 15:00."""
    rule = {
        "reminder_added": {"words": ["tax"], "due": {"at": "day_after_tomorrow 15:00"}}
    }
    good = datetime(2026, 10, 13, 15, 0, tzinfo=IST)
    bad = datetime(2026, 10, 12, 15, 0, tzinfo=IST)
    assert run_grade(rule, db={"notes": [], "reminders": [rem("tax", good)]})[0] is True
    assert run_grade(rule, db={"notes": [], "reminders": [rem("tax", bad)]})[0] is False


def test_fr10_grade_reminder_added_in_minutes_tolerance_edges():
    """in_minutes accepts asked_at + n min within DUE_IN_TOLERANCE_S and rejects beyond."""
    tol = eval_config.DUE_IN_TOLERANCE_S
    rule = {"reminder_added": {"words": ["tea"], "due": {"in_minutes": 30}}}
    base = ASKED + timedelta(minutes=30)
    for delta, expected in [
        (0, True),
        (tol - 1, True),
        (-(tol - 1), True),
        (tol + 1, False),
        (-(tol + 1), False),
    ]:
        db = {
            "notes": [],
            "reminders": [rem("make tea", base + timedelta(seconds=delta))],
        }
        assert run_grade(rule, db=db)[0] is expected, delta


def test_fr10_grade_reminder_added_needs_all_words():
    """A reminder missing one of the words does not satisfy reminder_added."""
    db = {"notes": [], "reminders": [rem("dentist", TOMORROW_17)]}
    rule = {
        "reminder_added": {
            "words": ["dentist", "call"],
            "due": {"at": "tomorrow 17:00"},
        }
    }
    assert run_grade(rule, db=db)[0] is False


def test_fr10_grade_reminder_added_matches_any_status():
    """A stored reminder matches reminder_added whatever its status."""
    rule = {"reminder_added": {"words": ["dentist"], "due": {"at": "tomorrow 17:00"}}}
    for status in ("pending", "cancelled", "done", "missed"):
        db = {"notes": [], "reminders": [rem("dentist", TOMORROW_17, status)]}
        assert run_grade(rule, db=db)[0] is True, status


def test_fr10_grade_reminder_cancelled():
    """reminder_cancelled needs a cancelled reminder whose text has all the words."""
    rule = {"reminder_cancelled": ["dentist"]}
    cancelled = {
        "notes": [],
        "reminders": [rem("call dentist", TOMORROW_17, "cancelled")],
    }
    pending = {"notes": [], "reminders": [rem("call dentist", TOMORROW_17, "pending")]}
    other = {"notes": [], "reminders": [rem("water plants", TOMORROW_17, "cancelled")]}
    assert run_grade(rule, db=cancelled)[0] is True
    ok, reason = run_grade(rule, db=pending)
    assert ok is False
    assert "reminder_cancelled" in reason
    assert run_grade(rule, db=other)[0] is False


def test_fr10_grade_reminders_pending_exact_count():
    """reminders_pending counts only status 'pending' rows, exactly."""
    db = {
        "notes": [],
        "reminders": [
            rem("a", TOMORROW_17, "pending", 1),
            rem("b", TOMORROW_17, "cancelled", 2),
            rem("c", TOMORROW_17, "pending", 3),
        ],
    }
    assert run_grade({"reminders_pending": 2}, db=db)[0] is True
    ok, reason = run_grade({"reminders_pending": 3}, db=db)
    assert ok is False
    assert "reminders_pending" in reason
    assert run_grade({"reminders_pending": 1}, db=db)[0] is False


def test_fr5_grade_several_failures_all_listed_joined_by_semicolon():
    """All failing checks appear in the reason, joined by '; '."""
    rule = {
        "tools": ["add_note"],
        "searched": True,
        "answer_all": [["zebra"]],
        "notes_total": 4,
    }
    ok, reason = run_grade(rule, answer="hello")
    assert ok is False
    assert "tool add_note not called" in reason
    assert "searched" in reason
    assert "answer lacks one of" in reason
    assert "notes_total" in reason
    assert len(reason.split("; ")) >= 4


# ---------- expected_due / run-time resolution (FR-10) ----------


def test_fr10_expected_due_tomorrow_uses_askeds_date_and_zone():
    """'tomorrow HH:MM' is the next calendar day at that time in asked_at's zone, with the at tolerance."""
    when, tol = run_eval.expected_due({"at": "tomorrow 17:00"}, ASKED)
    assert when == TOMORROW_17
    assert when.utcoffset() == ASKED.utcoffset()
    assert tol == eval_config.DUE_AT_TOLERANCE_S


def test_fr10_expected_due_day_after_tomorrow_and_in_minutes():
    """day_after_tomorrow is +2 days; in_minutes is asked_at + n minutes with its own tolerance."""
    when, tol = run_eval.expected_due({"at": "day_after_tomorrow 15:00"}, ASKED)
    assert when == datetime(2026, 10, 13, 15, 0, tzinfo=IST)
    assert tol == eval_config.DUE_AT_TOLERANCE_S
    when, tol = run_eval.expected_due({"in_minutes": 45}, ASKED)
    assert when == ASKED + timedelta(minutes=45)
    assert tol == eval_config.DUE_IN_TOLERANCE_S


def test_fr10_expected_due_tomorrow_rolls_over_month_end():
    """'tomorrow' follows the run date across a month boundary."""
    asked = datetime(2026, 10, 31, 23, 50, tzinfo=IST)
    when, _ = run_eval.expected_due({"at": "tomorrow 17:00"}, asked)
    assert when == datetime(2026, 11, 1, 17, 0, tzinfo=IST)


def test_fr10_tomorrow_resolves_at_run_time_not_fixed_date():
    """The same rule accepts a different due_at when the run happens on a different day."""
    rule = {"reminder_added": {"words": ["dentist"], "due": {"at": "tomorrow 17:00"}}}
    q = {"id": "q", "group": "reminders", "pass": rule}
    day1 = datetime(2026, 10, 11, 9, 0, tzinfo=IST)
    day2 = datetime(2026, 12, 3, 22, 0, tzinfo=IST)
    due1 = datetime(2026, 10, 12, 17, 0, tzinfo=IST)
    due2 = datetime(2026, 12, 4, 17, 0, tzinfo=IST)
    r1 = make_result(db={"notes": [], "reminders": [rem("dentist", due1)]}, asked=day1)
    r2 = make_result(db={"notes": [], "reminders": [rem("dentist", due2)]}, asked=day2)
    assert run_eval.grade(q, r1)[0] is True
    assert run_eval.grade(q, r2)[0] is True
    stale = make_result(
        db={"notes": [], "reminders": [rem("dentist", due1)]}, asked=day2
    )
    assert run_eval.grade(q, stale)[0] is False


# ---------- snapshot_db ----------


def test_fr9_snapshot_db_reads_notes_and_reminders(env):
    """snapshot_db returns notes {id,text} and reminders {id,text,due_at,status} from the eval DB."""
    snap = run_eval.snapshot_db()
    assert sorted(n["text"] for n in snap["notes"]) == ["buy milk", "call dad"]
    assert all({"id", "text"} <= set(n) for n in snap["notes"])
    assert len(snap["reminders"]) == 1
    r = snap["reminders"][0]
    assert r["text"] == "take pills"
    assert r["due_at"] == DUE
    assert r["status"] == "pending"
    assert "id" in r


# ---------- run_one / replay with grading ----------


class WritingServer(FakeServer):
    """FakeServer that also adds a note while handling the request."""

    def __call__(self, request):
        store.add_note("added during post", CREATED)
        return super().__call__(request)


@pytest.fixture
def fixed_now(monkeypatch):
    monkeypatch.setattr(run_eval, "now", lambda: ASKED)
    return ASKED


def test_fr9_run_one_sets_asked_at_db_passed_reason(env, fixed_now):
    """run_one adds asked_at (ISO with offset), db snapshot, passed and reason."""
    write_clips(questions(1))
    server = FakeServer(tool_calls={1: [{"name": "add_note", "args": {}, "ok": True}]})
    q = {
        "id": "q01",
        "group": "notes",
        "pass": {"tools": ["add_note"], "notes_total": 2},
    }
    with make_client(server) as client:
        result = run_eval.run_one(client, q, clock=Clock())
    assert result["asked_at"] == ASKED.isoformat()
    assert datetime.fromisoformat(result["asked_at"]).utcoffset() is not None
    assert len(result["db"]["notes"]) == 2
    assert len(result["db"]["reminders"]) == 1
    assert result["passed"] is True
    assert result["reason"] == "ok"


def test_fr9_run_one_failing_check_gives_reason(env, fixed_now):
    """A failed check sets passed false and a reason naming it."""
    write_clips(questions(1))
    q = {"id": "q01", "group": "notes", "pass": {"tools": ["add_note"]}}
    with make_client(FakeServer()) as client:
        result = run_eval.run_one(client, q, clock=Clock())
    assert result["passed"] is False
    assert "tool add_note not called" in result["reason"]


def test_fr9_run_one_snapshots_db_after_the_post(env, fixed_now):
    """The DB snapshot is taken after the POST, so rows the server wrote are in it."""
    write_clips(questions(1))
    q = {
        "id": "q01",
        "group": "notes",
        "pass": {"notes_total": 3, "note_added": ["during"]},
    }
    with make_client(WritingServer()) as client:
        result = run_eval.run_one(client, q, clock=Clock())
    assert len(result["db"]["notes"]) == 3
    assert result["passed"] is True


def test_fr10_run_one_asked_at_taken_before_the_post(env, monkeypatch):
    """asked_at is read before the POST, not after."""
    write_clips(questions(1))
    times = iter([ASKED, ASKED + timedelta(hours=5)])
    monkeypatch.setattr(run_eval, "now", lambda: next(times))
    with make_client(FakeServer()) as client:
        result = run_eval.run_one(
            client, {"id": "q01", "group": "general"}, clock=Clock()
        )
    assert result["asked_at"] == ASKED.isoformat()


def test_fr9_run_one_500_still_snapshots_db_and_fails(env, fixed_now):
    """A failed request still gets a db snapshot, passed false and a reason starting 'http 500'."""
    write_clips(questions(1))
    with make_client(FakeServer(status={1: 500})) as client:
        result = run_eval.run_one(
            client, {"id": "q01", "group": "general"}, clock=Clock()
        )
    assert len(result["db"]["notes"]) == 2
    assert result["passed"] is False
    assert result["reason"].startswith("http 500")
    assert "llm: broke" in result["reason"]


def test_fr5_run_one_connection_error_fails_with_db(env, fixed_now):
    """A connection error (no status, no log) fails and still carries a db snapshot."""
    write_clips(questions(1))
    with make_client(FakeServer(fail={1})) as client:
        result = run_eval.run_one(
            client, {"id": "q01", "group": "general"}, clock=Clock()
        )
    assert result["passed"] is False
    assert result["reason"] != "ok"
    assert len(result["db"]["notes"]) == 2


def test_fr5_replay_progress_line_shows_pass_or_fail(env, fixed_now, capsys):
    """The replay progress line for each question says PASS or FAIL."""
    qs = questions(2)
    write_clips(qs)
    with make_client(FakeServer(status={2: 500})) as client:
        results = run_eval.replay(qs, client, sleep=lambda s: None, clock=Clock())
    out = capsys.readouterr().out
    assert "PASS" in out and "FAIL" in out
    assert [r["passed"] for r in results] == [True, False]
