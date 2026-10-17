"""Tests for eval/run_eval_v2.py, the v2 eval runner, T3 part: safety, files, resume, case replay (FR-16, FR-17, FR-22).

Temp DB, fake server (httpx.MockTransport), fake sleep/clock. No network, models or real sleeping.
"""

import json
import sqlite3

import httpx
import pytest

from eval import config as eval_config
from eval import record, run_eval
from eval import run_eval_v2 as ev2
from server import store

REAL_CLIENT = httpx.Client
CREATED = "2026-10-09T10:00:00+05:30"
DUE = "2026-10-10T10:00:00+05:30"
CLIP = b"RIFF-fake-clip-"
SHOT = b"\xff\xd8fake-jpeg-"
TABLES = ("notes", "reminders", "concepts")


def counts(path) -> tuple[int, int, int]:
    con = sqlite3.connect(path)
    try:
        return tuple(
            con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES
        )
    finally:
        con.close()


def data_v2() -> dict:
    return {
        "quiz_start": "Quiz me.",
        "rows": [
            {
                "id": "look01",
                "group": "look",
                "spoken": "What is this?",
                "screenshot": "look01.jpg",
            },
            {
                "id": "look02",
                "group": "look",
                "spoken": "And this?",
                "screenshot": "look02.jpg",
            },
            {
                "id": "fu01",
                "group": "followup",
                "spoken": "Who wrote Hamlet?",
                "followup": "When?",
            },
            {"id": "c01", "group": "concept", "spoken": "I learned photosynthesis."},
            {
                "id": "qz01",
                "group": "quiz",
                "spoken": "Light.",
                "seed": {"name": "photosynthesis"},
            },
        ],
    }


def write_files(data: dict) -> None:
    eval_config.CLIP_DIR_V2.mkdir(parents=True, exist_ok=True)
    eval_config.SCREENSHOT_DIR_V2.mkdir(parents=True, exist_ok=True)
    for item in record.v2_items(data):
        (eval_config.CLIP_DIR_V2 / f"{item['id']}.wav").write_bytes(
            CLIP + item["id"].encode()
        )
    for row in data["rows"]:
        if row["group"] == "look":
            (eval_config.SCREENSHOT_DIR_V2 / row["screenshot"]).write_bytes(
                SHOT + row["id"].encode()
            )


@pytest.fixture
def env(db, monkeypatch, tmp_path):
    """Seeded temp DB (1 note, 1 reminder, 1 concept) and v2 eval config under tmp_path."""
    store.add_note("buy milk", CREATED)
    store.add_reminder("take pills", DUE, CREATED)
    store.log_concept("gravity", "things fall", CREATED)
    clip_dir = tmp_path / "eval_v2"
    clip_dir.mkdir()
    monkeypatch.setattr(eval_config, "DB_PATH", db)
    monkeypatch.setattr(eval_config, "LOG_PATH", tmp_path / "queries.jsonl")
    monkeypatch.setattr(eval_config, "CLIP_DIR_V2", clip_dir)
    monkeypatch.setattr(eval_config, "SCREENSHOT_DIR_V2", clip_dir / "screenshots")
    monkeypatch.setattr(eval_config, "MARKER_PATH_V2", clip_dir / "restore-pending")
    monkeypatch.setattr(eval_config, "PROGRESS_PATH_V2", clip_dir / "progress.json")
    monkeypatch.setattr(eval_config, "QUESTIONS_V2_PATH", tmp_path / "q2.json")
    monkeypatch.setattr(eval_config, "SERVER_URL", "http://fake")
    return db


def append_log(entry: dict) -> None:
    with eval_config.LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        self.t += 1.0
        return self.t


class FakeServer:
    """MockTransport handler: /health, /session/reset, /query (appends a log line)."""

    def __init__(self, tool_calls=None, status=None, fail=None, health=200):
        self.paths: list[str] = []
        self.queries: list[httpx.Request] = []
        self.resets = 0
        self.tool_calls = tool_calls or {}
        self.status = status or {}  # query index (1-based) -> status
        self.fail = fail or set()
        self.health = health

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.paths.append(path)
        if path == "/health":
            return httpx.Response(self.health, json={"status": "ok"})
        if path == "/session/reset":
            self.resets += 1
            return httpx.Response(200, json={"status": "ok"})
        self.queries.append(request)
        n = len(self.queries)
        if n in self.fail:
            raise httpx.ConnectError("boom")
        code = self.status.get(n, 200)
        entry = {
            "question": f"asked {n}",
            "answer": "fake answer",
            "searched": False,
            "tool_calls": self.tool_calls.get(n, []),
            "image_sent": b'name="image"' in request.content,
            "session_continued": False,
            "concept": None,
            "timings_ms": {"stt": 1, "llm": 2, "tts": 3},
        }
        if code != 200:
            entry["error"] = "llm: broke"
            append_log(entry)
            return httpx.Response(code, json={"error": "llm: broke"})
        append_log(entry)
        return httpx.Response(
            200, content=b"RIFF-answer", headers={"content-type": "audio/wav"}
        )


def make_client(server) -> httpx.Client:
    return REAL_CLIENT(base_url="http://fake", transport=httpx.MockTransport(server))


def row_of(data: dict, row_id: str) -> dict:
    return next(r for r in data["rows"] if r["id"] == row_id)


# ---------- begin / end (FR-16) ----------


def test_fr16_begin_backs_up_then_clears_notes_reminders_and_concepts(env):
    """begin() backs up the DB, then empties notes, reminders and concepts; the file stays."""
    ev2.begin()
    assert env.exists()
    assert counts(env) == (0, 0, 0)
    backups = list(eval_config.CLIP_DIR_V2.glob("backup-*.db"))
    assert len(backups) == 1
    assert counts(backups[0]) == (1, 1, 1)


def test_fr16_marker_holds_backup_path(env):
    """The restore-pending marker holds the path of the backup file."""
    ev2.begin()
    backup = next(eval_config.CLIP_DIR_V2.glob("backup-*.db"))
    assert eval_config.MARKER_PATH_V2.read_text(encoding="utf-8").strip() == str(backup)


def test_fr16_end_restores_all_three_tables_and_removes_marker(env):
    """end() restores notes, reminders and concepts and removes the marker."""
    ev2.begin()
    ev2.end()
    assert counts(env) == (1, 1, 1)
    assert not eval_config.MARKER_PATH_V2.exists()


def test_fr16_end_without_marker_does_nothing(env):
    """end() with no marker leaves the DB alone."""
    ev2.end()
    assert counts(env) == (1, 1, 1)


def test_fr16_leftover_marker_restored_before_new_backup(env):
    """A marker from a crashed run is restored first, so the new backup holds the user's rows."""
    ev2.begin()  # simulated crash: no end()
    assert counts(env) == (0, 0, 0)
    ev2.begin()
    marker = eval_config.MARKER_PATH_V2.read_text(encoding="utf-8").strip()
    assert counts(marker) == (1, 1, 1)
    ev2.end()
    assert counts(env) == (1, 1, 1)


def test_fr16_missing_backup_in_marker_raises_and_changes_nothing(env):
    """A marker naming a missing backup raises RuntimeError and leaves the DB untouched."""
    eval_config.MARKER_PATH_V2.write_text(
        str(eval_config.CLIP_DIR_V2 / "backup-gone.db"), encoding="utf-8"
    )
    with pytest.raises(RuntimeError):
        ev2.begin()
    assert counts(env) == (1, 1, 1)
    assert eval_config.MARKER_PATH_V2.exists()
    assert list(eval_config.CLIP_DIR_V2.glob("backup-*.db")) == []


# ---------- check_files / clip_ids / select ----------


def test_fr22_check_files_lists_missing_clips_and_screenshots(env):
    """check_files names every missing <id>.wav and look screenshot; empty when all exist."""
    data = data_v2()
    assert set(ev2.check_files(data)) >= {
        "quiz_start.wav",
        "look01.wav",
        "fu01_2.wav",
        "look01.jpg",
        "look02.jpg",
    }
    write_files(data)
    assert ev2.check_files(data) == []
    (eval_config.CLIP_DIR_V2 / "fu01_2.wav").unlink()
    (eval_config.SCREENSHOT_DIR_V2 / "look02.jpg").unlink()
    assert sorted(ev2.check_files(data)) == ["fu01_2.wav", "look02.jpg"]


def test_fr22_clip_ids_per_group():
    """look/concept: [id]; followup: [id, id_2]; quiz: [quiz_start, id]."""
    data = data_v2()
    assert ev2.clip_ids(row_of(data, "look01")) == ["look01"]
    assert ev2.clip_ids(row_of(data, "c01")) == ["c01"]
    assert ev2.clip_ids(row_of(data, "fu01")) == ["fu01", "fu01_2"]
    assert ev2.clip_ids(row_of(data, "qz01")) == ["quiz_start", "qz01"]


def test_fr22_select_all_and_by_group_keeps_file_order():
    """select(None) returns every row; select(group) only that group, in file order."""
    data = data_v2()
    assert [r["id"] for r in ev2.select(data, None)] == [r["id"] for r in data["rows"]]
    assert [r["id"] for r in ev2.select(data, "look")] == ["look01", "look02"]
    assert [r["id"] for r in ev2.select(data, "quiz")] == ["qz01"]


# ---------- progress ----------


def test_fr17_progress_roundtrip_and_clear(env):
    """save_progress/load_progress round-trip; load is {} when missing; clear is safe twice."""
    assert ev2.load_progress() == {}
    ev2.save_progress({"look01": {"id": "look01", "passed": True}})
    assert ev2.load_progress() == {"look01": {"id": "look01", "passed": True}}
    assert eval_config.PROGRESS_PATH_V2.exists()
    ev2.clear_progress()
    assert not eval_config.PROGRESS_PATH_V2.exists()
    assert ev2.load_progress() == {}
    ev2.clear_progress()


# ---------- run_case ----------


def run(data, row_id, server, sleep=None, clock=None):
    slept = [] if sleep is None else sleep
    with make_client(server) as client:
        return ev2.run_case(
            client, row_of(data, row_id), sleep=slept.append, clock=clock or Clock()
        )


def test_fr22_look_case_resets_once_and_sends_audio_and_screenshot(env):
    """A look case POSTs /session/reset, then /query with the clip as audio and the screenshot as image/jpeg."""
    data = data_v2()
    write_files(data)
    server = FakeServer()
    result = run(data, "look01", server)
    assert server.paths == ["/session/reset", "/query"]
    req = server.queries[0]
    assert b'name="audio"' in req.content and b"audio/wav" in req.content
    assert CLIP + b"look01" in req.content
    assert b'name="image"' in req.content and b"image/jpeg" in req.content
    assert SHOT + b"look01" in req.content
    assert result["id"] == "look01" and result["group"] == "look"
    assert len(result["turns"]) == 1
    turn = result["turns"][0]
    assert turn["clip"] == "look01" and turn["status"] == 200
    assert turn["error"] is None and turn["wall_s"] > 0
    assert turn["log"]["image_sent"] is True
    assert result["passed"] is True and result["reason"] == "ok"


def test_fr22_non_look_case_sends_no_image(env):
    """A concept case sends audio only, no image field."""
    data = data_v2()
    write_files(data)
    server = FakeServer()
    run(data, "c01", server)
    assert b'name="image"' not in server.queries[0].content
    assert CLIP + b"c01" in server.queries[0].content


def test_fr22_followup_two_turns_in_one_session(env):
    """A follow-up case sends its two clips in order after one single reset; no image."""
    data = data_v2()
    write_files(data)
    server = FakeServer()
    result = run(data, "fu01", server)
    assert server.paths == ["/session/reset", "/query", "/query"]
    assert server.resets == 1
    assert CLIP + b"fu01" in server.queries[0].content
    assert CLIP + b"fu01_2" in server.queries[1].content
    assert all(b'name="image"' not in q.content for q in server.queries)
    assert [t["clip"] for t in result["turns"]] == ["fu01", "fu01_2"]
    assert result["passed"] is True


def test_fr22_quiz_case_sends_start_clip_then_answer_clip(env):
    """A quiz case sends quiz_start.wav, then its own clip, in one session."""
    data = data_v2()
    write_files(data)
    server = FakeServer()
    result = run(data, "qz01", server)
    assert server.resets == 1
    assert CLIP + b"quiz_start" in server.queries[0].content
    assert CLIP + b"qz01" in server.queries[1].content
    assert [t["clip"] for t in result["turns"]] == ["quiz_start", "qz01"]


def test_fr22_each_case_resets_session_before_its_queries(env):
    """Running three cases in a row gives reset, query(ies), reset, ... one reset per case."""
    data = data_v2()
    write_files(data)
    server = FakeServer()
    with make_client(server) as client:
        for rid in ("look01", "fu01", "c01"):
            ev2.run_case(client, row_of(data, rid), sleep=lambda s: None, clock=Clock())
    assert server.paths == [
        "/session/reset",
        "/query",
        "/session/reset",
        "/query",
        "/query",
        "/session/reset",
        "/query",
    ]


def test_fr16_run_case_paces_four_seconds_per_gemini_call(env):
    """After each query it sleeps SECONDS_PER_CALL * calls - wall_s (1 call = 4 s total)."""
    data = data_v2()
    write_files(data)
    server = FakeServer(tool_calls={2: [{"name": "a"}, {"name": "b"}]})
    slept = []
    result = run(data, "fu01", server, sleep=slept)
    per = eval_config.SECONDS_PER_CALL
    t1, t2 = result["turns"]
    assert slept == [
        pytest.approx(per * 1 - t1["wall_s"]),
        pytest.approx(per * 3 - t2["wall_s"]),
    ]
    assert run_eval.gemini_calls(t2["log"]) == 3


def test_fr17_turn_log_is_last_line_written_during_the_call(env):
    """Each turn's log is the new JSONL line from that call, not an older one."""
    data = data_v2()
    write_files(data)
    append_log({"question": "old"})
    server = FakeServer()
    result = run(data, "fu01", server)
    assert [t["log"]["question"] for t in result["turns"]] == ["asked 1", "asked 2"]


def test_fr16_run_case_records_500_and_returns(env):
    """A 500 is recorded with status and error text, the case fails with 'http 500: ...' and nothing raises."""
    data = data_v2()
    write_files(data)
    result = run(data, "look01", FakeServer(status={1: 500}))
    turn = result["turns"][0]
    assert turn["status"] == 500 and turn["error"] == "llm: broke"
    assert result["passed"] is False
    assert result["reason"] == "http 500: llm: broke"


def test_fr16_run_case_connection_error_does_not_raise(env):
    """A connection error is recorded in the turn and the case fails without raising."""
    data = data_v2()
    write_files(data)
    result = run(data, "look01", FakeServer(fail={1}))
    turn = result["turns"][0]
    assert "boom" in turn["error"]
    assert turn["log"] is None
    assert result["passed"] is False


def test_fr16_followup_second_turn_failure_fails_case(env):
    """A 500 on the second turn fails the case with that turn's http reason."""
    data = data_v2()
    write_files(data)
    result = run(data, "fu01", FakeServer(status={2: 500}))
    assert result["turns"][1]["status"] == 500
    assert result["passed"] is False
    assert result["reason"].startswith("http 500")


def test_fr17_run_case_without_log_line_fails(env, monkeypatch):
    """Status 200 but no log line gives passed False and reason 'no log line'."""
    data = data_v2()
    write_files(data)
    server = FakeServer()

    def silent(request):
        resp = server(request)
        eval_config.LOG_PATH.unlink(missing_ok=True)
        return resp

    with make_client(silent) as client:
        result = ev2.run_case(
            client, row_of(data, "c01"), sleep=lambda s: None, clock=Clock()
        )
    assert result["turns"][0]["log"] is None
    assert result["passed"] is False
    assert result["reason"] == "no log line"


# ---------- main ----------


@pytest.fixture
def main_env(env, monkeypatch):
    data = data_v2()
    eval_config.QUESTIONS_V2_PATH.write_text(json.dumps(data), encoding="utf-8")
    write_files(data)
    state = {"server": FakeServer(), "data": data, "env": env}

    def factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return REAL_CLIENT(
            *args, transport=httpx.MockTransport(state["server"]), **kwargs
        )

    monkeypatch.setattr(ev2.httpx, "Client", factory)
    real = ev2.run_case
    state["calls"] = []

    def fast(client, row, *a, **k):
        state["calls"].append(row["id"])
        if state.get("interrupt_on") == row["id"]:
            raise KeyboardInterrupt
        return real(client, row, sleep=lambda s: None, clock=Clock())

    monkeypatch.setattr(ev2, "run_case", fast)
    return state


def untouched(state) -> bool:
    return (
        counts(state["env"]) == (1, 1, 1)
        and not eval_config.MARKER_PATH_V2.exists()
        and list(eval_config.CLIP_DIR_V2.glob("backup-*.db")) == []
    )


def test_fr22_main_runs_all_rows_saves_progress_and_restores_db(main_env):
    """main with no args runs every row once, saves each to progress.json, returns 0, restores the DB."""
    assert ev2.main([]) == 0
    assert main_env["calls"] == ["look01", "look02", "fu01", "c01", "qz01"]
    assert set(ev2.load_progress()) == set(main_env["calls"])
    assert counts(main_env["env"]) == (1, 1, 1)
    assert not eval_config.MARKER_PATH_V2.exists()


def test_fr22_main_clears_db_while_running(main_env, monkeypatch):
    """The DB is empty while cases run (begin() was called first)."""
    seen = []
    inner = ev2.run_case

    def spy(client, row, *a, **k):
        seen.append(counts(main_env["env"]))
        return inner(client, row)

    monkeypatch.setattr(ev2, "run_case", spy)
    ev2.main(["--group", "concept"])
    assert seen == [(0, 0, 0)]


def test_fr22_main_group_selects_only_that_group(main_env):
    """--group followup runs only follow-up rows."""
    assert ev2.main(["--group", "followup"]) == 0
    assert main_env["calls"] == ["fu01"]
    assert set(ev2.load_progress()) == {"fu01"}


def test_fr22_main_rejects_unknown_group(main_env):
    """--group outside look/followup/concept/quiz is an argparse error (SystemExit)."""
    with pytest.raises(SystemExit):
        ev2.main(["--group", "nope"])


def test_fr22_main_resume_skips_finished_cases(main_env):
    """Cases already in progress.json are skipped on the next run."""
    ev2.save_progress({"look01": {"id": "look01", "group": "look", "passed": True}})
    assert ev2.main([]) == 0
    assert main_env["calls"] == ["look02", "fu01", "c01", "qz01"]
    assert ev2.load_progress()["look01"] == {
        "id": "look01",
        "group": "look",
        "passed": True,
    }


def test_fr22_main_fresh_clears_progress_and_reruns_all(main_env):
    """--fresh discards earlier progress and runs every selected row again."""
    ev2.save_progress({"look01": {"id": "look01", "passed": True}})
    assert ev2.main(["--fresh"]) == 0
    assert main_env["calls"] == ["look01", "look02", "fu01", "c01", "qz01"]


def test_fr22_main_keyboard_interrupt_restores_db_and_keeps_progress(main_env):
    """Ctrl+C mid-run still restores the DB and the cases finished before it stay in progress.json."""
    main_env["interrupt_on"] = "fu01"
    with pytest.raises(KeyboardInterrupt):
        ev2.main([])
    assert counts(main_env["env"]) == (1, 1, 1)
    assert not eval_config.MARKER_PATH_V2.exists()
    assert set(ev2.load_progress()) == {"look01", "look02"}


def test_fr22_main_saves_each_case_immediately(main_env):
    """Progress is written after every case, not only at the end."""
    main_env["interrupt_on"] = "look02"
    with pytest.raises(KeyboardInterrupt):
        ev2.main([])
    assert set(ev2.load_progress()) == {"look01"}


def test_fr16_main_continues_after_500(main_env):
    """A 500 in one case is recorded as a failed case and the next cases still run."""
    main_env["server"] = FakeServer(status={1: 500})
    assert ev2.main([]) == 0
    progress = ev2.load_progress()
    assert progress["look01"]["passed"] is False
    assert progress["look02"]["passed"] is True
    assert len(progress) == 5


def test_fr16_main_returns_1_when_health_fails(main_env, capsys):
    """/health not 200: message, return 1, DB untouched, no cases run."""
    main_env["server"] = FakeServer(health=503)
    assert ev2.main([]) == 1
    assert capsys.readouterr().out.strip() != ""
    assert untouched(main_env)
    assert main_env["calls"] == []


def test_fr22_main_returns_1_naming_missing_files(main_env, capsys):
    """Missing clip or screenshot for the selected rows: names them, points to eval.record --set v2, DB untouched."""
    (eval_config.CLIP_DIR_V2 / "fu01_2.wav").unlink()
    (eval_config.SCREENSHOT_DIR_V2 / "look02.jpg").unlink()
    assert ev2.main([]) == 1
    out = capsys.readouterr().out
    assert "fu01_2.wav" in out and "look02.jpg" in out
    assert "eval.record --set v2" in out
    assert untouched(main_env)


def test_fr22_main_only_checks_files_of_selected_group(main_env):
    """A missing file for a group that is not selected does not block the run."""
    (eval_config.SCREENSHOT_DIR_V2 / "look01.jpg").unlink()
    assert ev2.main(["--group", "concept"]) == 0
    assert main_env["calls"] == ["c01"]
