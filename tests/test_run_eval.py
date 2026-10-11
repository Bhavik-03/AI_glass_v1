"""Tests for eval/run_eval.py, the eval replay runner (FR-16, FR-17).

Temp DB, fake server (httpx.MockTransport), fake sleep/clock/process list.
No network, models, real sleeping or real PowerShell.
"""

import json
import sqlite3
import subprocess

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
            entry = {"question": f"asked {n}", "tool_calls": self.tool_calls.get(n, [])}
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
