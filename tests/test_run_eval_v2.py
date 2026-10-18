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

    def __init__(
        self,
        tool_calls=None,
        status=None,
        fail=None,
        health=200,
        answers=None,
        continued=None,
        timings=None,
    ):
        self.answers = answers or {}  # query index (1-based) -> logged answer
        self.continued = continued or {}  # query index -> session_continued
        self.timings = timings or {}  # query index -> timings_ms
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
            "answer": self.answers.get(n, "fake answer"),
            "searched": False,
            "tool_calls": self.tool_calls.get(n, []),
            "image_sent": b'name="image"' in request.content,
            "session_continued": self.continued.get(n, False),
            "concept": None,
            "timings_ms": self.timings.get(n, {"stt": 1, "llm": 2, "tts": 3}),
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
    server = FakeServer(continued={2: True})
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


# ---------- grading (T4: FR-19, FR-20, FR-21) ----------


def look_row(words=(("apple",),)) -> dict:
    row = dict(row_of(data_v2(), "look01"))
    row["pass"] = {"answer_all": [list(alts) for alts in words]}
    return row


def followup_row(words=(("1603", "sixteen"),)) -> dict:
    row = dict(row_of(data_v2(), "fu01"))
    row["pass"] = {"answer_all": [list(alts) for alts in words]}
    return row


def run_row(row, server):
    write_files(data_v2())
    with make_client(server) as client:
        return ev2.run_case(client, row, sleep=lambda s: None, clock=Clock())


def test_fr19_look_passes_when_answer_has_words_and_image_sent(env):
    """Look passes when the logged answer holds the expected words and image_sent is true."""
    result = run_row(look_row(), FakeServer(answers={1: "It is a red Apple."}))
    assert result["passed"] is True and result["reason"] == "ok"


def test_fr19_look_fails_when_answer_lacks_expected_word(env):
    """Look fails with 'answer lacks one of [...]' when no alternative is in the answer."""
    result = run_row(look_row(), FakeServer(answers={1: "It is a pear."}))
    assert result["passed"] is False
    assert result["reason"] == "answer lacks one of ['apple']"


def test_fr19_look_alternatives_any_one_is_enough(env):
    """Each inner list is alternatives: one match satisfies it; all inner lists must be satisfied."""
    row = look_row((("apple", "fruit"), ("red", "green")))
    assert run_row(row, FakeServer(answers={1: "A fruit, green."}))["passed"] is True
    result = run_row(row, FakeServer(answers={1: "A fruit."}))
    assert result["passed"] is False
    assert result["reason"] == "answer lacks one of ['red', 'green']"


def test_fr19_look_match_is_case_insensitive_whole_word(env):
    """'pineapple' does not satisfy 'apple'; 'APPLE' does."""
    assert (
        run_row(look_row(), FakeServer(answers={1: "A pineapple."}))["passed"] is False
    )
    assert run_row(look_row(), FakeServer(answers={1: "APPLE!"}))["passed"] is True


def test_fr19_look_fails_when_log_says_image_not_sent(env):
    """Look fails with 'image_sent was false' when the log line says the image was not sent."""
    server = FakeServer(answers={1: "An apple."})

    def no_image(request):
        resp = server(request)
        if request.url.path != "/query":
            return resp
        lines = eval_config.LOG_PATH.read_text(encoding="utf-8").splitlines()
        entry = json.loads(lines[-1])
        entry["image_sent"] = False
        eval_config.LOG_PATH.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        return resp

    write_files(data_v2())
    with make_client(no_image) as client:
        result = ev2.run_case(client, look_row(), sleep=lambda s: None, clock=Clock())
    assert result["passed"] is False
    assert result["reason"] == "image_sent was false"


def test_fr19_look_both_failures_joined_with_semicolon(env):
    """Several failure reasons are joined with '; '."""
    server = FakeServer(answers={1: "A pear."})

    def no_image(request):
        resp = server(request)
        if request.url.path != "/query":
            return resp
        entry = json.loads(
            eval_config.LOG_PATH.read_text(encoding="utf-8").splitlines()[-1]
        )
        entry["image_sent"] = False
        eval_config.LOG_PATH.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        return resp

    write_files(data_v2())
    with make_client(no_image) as client:
        result = ev2.run_case(client, look_row(), sleep=lambda s: None, clock=Clock())
    assert result["reason"] == "answer lacks one of ['apple']; image_sent was false"


def test_fr19_look_http_failure_keeps_http_reason(env):
    """A 500 on a Look case still fails with the 'http 500: ...' reason."""
    result = run_row(look_row(), FakeServer(status={1: 500}))
    assert result["passed"] is False
    assert result["reason"] == "http 500: llm: broke"


def test_fr20_followup_passes_on_second_answer_and_session_continued(env):
    """A follow-up passes when the second answer has the words and the log shows session_continued."""
    server = FakeServer(
        answers={1: "A playwright.", 2: "Around 1603."}, continued={2: True}
    )
    result = run_row(followup_row(), server)
    assert result["passed"] is True and result["reason"] == "ok"


def test_fr20_followup_fails_when_session_not_continued(env):
    """A follow-up fails with 'session was not continued' when the second log has session_continued false."""
    server = FakeServer(answers={2: "Around 1603."}, continued={2: False})
    result = run_row(followup_row(), server)
    assert result["passed"] is False
    assert result["reason"] == "session was not continued"


def test_fr20_followup_fails_when_second_answer_lacks_words(env):
    """A follow-up fails when the second answer lacks the expected words."""
    server = FakeServer(answers={2: "I do not know."}, continued={2: True})
    result = run_row(followup_row(), server)
    assert result["passed"] is False
    assert result["reason"] == "answer lacks one of ['1603', 'sixteen']"


def test_fr20_followup_first_answer_is_not_graded(env):
    """Only the last turn is graded: a first answer without the words, and session_continued false on turn 1, do not fail."""
    server = FakeServer(
        answers={1: "nothing relevant", 2: "Sixteen hundred."},
        continued={1: False, 2: True},
    )
    assert run_row(followup_row(), server)["passed"] is True


def test_fr20_followup_first_turn_500_fails_with_http_reason(env):
    """A 500 on the first turn fails the case with that http reason."""
    result = run_row(followup_row(), FakeServer(status={1: 500}))
    assert result["passed"] is False
    assert result["reason"].startswith("http 500")


def test_fr21_result_has_transcript_answer_tools_and_timings_of_last_turn(env):
    """The case result carries the graded (last) turn's transcript, answer, tool names and stt/llm/tts/total seconds."""
    server = FakeServer(
        answers={1: "first", 2: "Around 1603."},
        continued={2: True},
        tool_calls={2: [{"name": "web_search"}, {"name": "log_concept"}]},
        timings={
            1: {"stt": 9000, "llm": 9000, "tts": 9000},
            2: {"stt": 500, "llm": 2000, "tts": 250},
        },
    )
    result = run_row(followup_row(), server)
    assert result["transcript"] == "asked 2"
    assert result["answer"] == "Around 1603."
    assert result["tools"] == ["web_search", "log_concept"]
    assert result["stt_s"] == pytest.approx(0.5)
    assert result["llm_s"] == pytest.approx(2.0)
    assert result["tts_s"] == pytest.approx(0.25)
    assert result["total_s"] == pytest.approx(2.75)


def test_fr21_look_result_fields_from_single_turn(env):
    """A single-turn case reports its own turn's fields."""
    server = FakeServer(
        answers={1: "An apple."}, timings={1: {"stt": 1000, "llm": 3000, "tts": 500}}
    )
    result = run_row(look_row(), server)
    assert result["transcript"] == "asked 1"
    assert result["answer"] == "An apple."
    assert result["tools"] == []
    assert result["total_s"] == pytest.approx(4.5)


def test_fr21_result_without_log_has_empty_fields_and_wall_total(env):
    """Without a log line: transcript None, answer '', tools [], stage times 0.0, total_s is the turn's wall_s."""
    result = run_row(look_row(), FakeServer(fail={1}))
    turn = result["turns"][0]
    assert result["transcript"] is None
    assert result["answer"] == ""
    assert result["tools"] == []
    assert result["stt_s"] == 0.0
    assert result["llm_s"] == 0.0
    assert result["tts_s"] == 0.0
    assert result["total_s"] == pytest.approx(turn["wall_s"])


def test_fr21_failed_followup_second_turn_reports_that_turn(env):
    """When the second turn fails, the result fields come from the last turn run (wall_s total if no log)."""
    result = run_row(followup_row(), FakeServer(fail={2}))
    assert result["transcript"] is None
    assert result["total_s"] == pytest.approx(result["turns"][1]["wall_s"])


def test_fr21_result_is_saved_in_progress_with_new_fields(main_env):
    """main saves the new per-case fields in progress.json."""
    assert ev2.main(["--group", "concept"]) == 0
    saved = ev2.load_progress()["c01"]
    for key in ("transcript", "answer", "tools", "stt_s", "llm_s", "tts_s", "total_s"):
        assert key in saved
    assert saved["transcript"] == "asked 1"


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
    earlier = case("look01", "look", passed=True)
    ev2.save_progress({"look01": earlier})
    assert ev2.main([]) == 0
    assert main_env["calls"] == ["look02", "fu01", "c01", "qz01"]
    assert ev2.load_progress()["look01"] == earlier


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


# ---------- concept and quiz grading (T5: FR-23, FR-24) ----------


def concept_names() -> list[str]:
    con = sqlite3.connect(eval_config.DB_PATH)
    try:
        return [r[0] for r in con.execute("SELECT name FROM concepts")]
    finally:
        con.close()


def stored_status(name: str):
    con = sqlite3.connect(eval_config.DB_PATH)
    try:
        row = con.execute(
            "SELECT status FROM concepts WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def set_status(name: str, status: str) -> None:
    con = sqlite3.connect(eval_config.DB_PATH)
    try:
        with con:
            con.execute(
                "UPDATE concepts SET status = ? WHERE name = ? COLLATE NOCASE",
                (status, name),
            )
    finally:
        con.close()


def set_log_concept(value) -> None:
    """Rewrite the last log line with the given concept value."""
    lines = eval_config.LOG_PATH.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[-1])
    entry["concept"] = value
    lines[-1] = json.dumps(entry)
    eval_config.LOG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def hooked(server, on_query):
    """Handler wrapper: after a successful fake /query, call on_query(n) (n = 1-based)."""

    def handler(request):
        resp = server(request)
        if request.url.path == "/query" and resp.status_code == 200:
            on_query(len(server.queries))
        return resp

    return handler


def run_hooked(row, server, on_query):
    write_files(data_v2())
    with make_client(hooked(server, on_query)) as client:
        return ev2.run_case(client, row, sleep=lambda s: None, clock=Clock())


def concept_row(added: bool = True) -> dict:
    row = dict(row_of(data_v2(), "c01"))
    row["pass"] = {"concept_added": added}
    return row


def quiz_row(status: str = "right") -> dict:
    row = dict(row_of(data_v2(), "qz01"))
    row["seed"] = {"name": "Photosynthesis", "summary": "plants make sugar from light"}
    row["pass"] = {"status": status}
    return row


def test_fr23_concept_passes_when_one_row_added_and_log_concept_set(env):
    """Concept row passes when exactly one concept row is added and the log concept is set."""

    def on_query(n):
        store.log_concept("gradient descent", "minimise loss", CREATED)
        set_log_concept("gradient descent")

    result = run_hooked(concept_row(), FakeServer(), on_query)
    assert result["passed"] is True and result["reason"] == "ok"


def test_fr23_concept_fails_when_no_row_added(env):
    """Concept row fails with 'concept not added' when the table did not grow."""

    result = run_hooked(concept_row(), FakeServer(), lambda n: set_log_concept("x"))
    assert result["passed"] is False
    assert "concept not added" in result["reason"]


def test_fr23_concept_existing_name_updated_counts_as_not_added(env):
    """Re-logging an existing name (a duplicate) updates the row, count unchanged: 'concept not added'."""

    def on_query(n):
        store.log_concept("gravity", "things fall down", CREATED)
        set_log_concept("gravity")

    result = run_hooked(concept_row(), FakeServer(), on_query)
    assert result["passed"] is False
    assert "concept not added" in result["reason"]
    assert concept_names().count("gravity") == 1


def test_fr23_concept_duplicate_name_case_insensitive_fails(env):
    """Two names equal ignoring case in the table fail with 'duplicate concept name'."""
    con = sqlite3.connect(eval_config.DB_PATH)
    try:
        with con:
            con.execute("DROP TABLE concepts")
            con.execute(
                "CREATE TABLE concepts (id INTEGER PRIMARY KEY, name TEXT, summary TEXT,"
                " first_asked TEXT, last_asked TEXT, status TEXT)"
            )
            con.execute(
                "INSERT INTO concepts (name, summary, first_asked, last_asked, status)"
                " VALUES ('Gravity', 's', ?, ?, 'new')",
                (CREATED, CREATED),
            )
    finally:
        con.close()

    def on_query(n):
        c = sqlite3.connect(eval_config.DB_PATH)
        try:
            with c:
                c.execute(
                    "INSERT INTO concepts (name, summary, first_asked, last_asked, status)"
                    " VALUES ('gravity', 's', ?, ?, 'new')",
                    (CREATED, CREATED),
                )
        finally:
            c.close()
        set_log_concept("gravity")

    result = run_hooked(concept_row(), FakeServer(), on_query)
    assert result["passed"] is False
    assert "duplicate concept name" in result["reason"]


def test_fr23_concept_fails_when_log_concept_is_none(env):
    """A row added but log concept None fails with 'log concept is None'."""

    def on_query(n):
        store.log_concept("gradient descent", "minimise loss", CREATED)

    result = run_hooked(concept_row(), FakeServer(), on_query)
    assert result["passed"] is False
    assert result["reason"] == "log concept is None"


def test_fr23_concept_fails_when_two_rows_added(env):
    """Adding two concept rows in one turn is not 'exactly one more': fails with 'concept not added'."""

    def on_query(n):
        store.log_concept("gradient descent", "a", CREATED)
        store.log_concept("loss function", "b", CREATED)
        set_log_concept("gradient descent")

    result = run_hooked(concept_row(), FakeServer(), on_query)
    assert result["passed"] is False
    assert "concept not added" in result["reason"]


def test_fr23_concept_expected_absent_passes_when_nothing_changes(env):
    """concept_added false passes when the count is unchanged and log concept is None."""
    result = run_hooked(concept_row(False), FakeServer(), lambda n: None)
    assert result["passed"] is True and result["reason"] == "ok"


def test_fr23_concept_expected_absent_fails_when_row_added(env):
    """concept_added false fails with 'concept added unexpectedly' when a row appears."""

    def on_query(n):
        store.log_concept("gradient descent", "a", CREATED)

    result = run_hooked(concept_row(False), FakeServer(), on_query)
    assert result["passed"] is False
    assert "concept added unexpectedly" in result["reason"]


def test_fr23_concept_expected_absent_fails_when_log_concept_set(env):
    """concept_added false fails when the log concept is set though no row was added."""
    result = run_hooked(
        concept_row(False), FakeServer(), lambda n: set_log_concept("gravity")
    )
    assert result["passed"] is False
    assert result["reason"] == "log concept is gravity but none expected"


def test_fr23_concept_reasons_joined_with_semicolon(env):
    """Several concept failures are joined with '; '."""
    result = run_hooked(concept_row(), FakeServer(), lambda n: None)
    assert result["passed"] is False
    assert result["reason"] == "concept not added; log concept is None"


def test_fr23_concept_http_failure_keeps_http_reason(env):
    """A 500 on a concept case still fails with the 'http 500: ...' reason."""
    result = run_hooked(concept_row(), FakeServer(status={1: 500}), lambda n: None)
    assert result["passed"] is False
    assert result["reason"] == "http 500: llm: broke"


def test_fr24_quiz_seeds_only_the_seed_concept_as_new(env):
    """Before the quiz, all concepts are deleted and the seed concept is inserted with status new."""
    seen = {}

    def on_query(n):
        if n == 1:
            seen["names"] = concept_names()
            seen["status"] = stored_status("Photosynthesis")

    run_hooked(quiz_row(), FakeServer(), on_query)
    assert seen["names"] == ["Photosynthesis"]
    assert seen["status"] == "new"


def test_fr24_quiz_seeds_before_session_reset(env):
    """The seed is in the DB by the time /session/reset is called."""
    seen = {}
    server = FakeServer()

    def handler(request):
        if request.url.path == "/session/reset":
            seen["names"] = concept_names()
        return server(request)

    write_files(data_v2())
    with make_client(handler) as client:
        ev2.run_case(client, quiz_row(), sleep=lambda s: None, clock=Clock())
    assert seen["names"] == ["Photosynthesis"]


def test_fr24_quiz_sends_start_clip_then_answer_clip(env):
    """Quiz sends quiz_start.wav, then the row's own clip, after one reset."""
    server = FakeServer()
    result = run_hooked(quiz_row(), server, lambda n: None)
    assert server.resets == 1
    assert CLIP + b"quiz_start" in server.queries[0].content
    assert CLIP + b"qz01" in server.queries[1].content
    assert [t["clip"] for t in result["turns"]] == ["quiz_start", "qz01"]


@pytest.mark.parametrize("expected", ["right", "wrong"])
def test_fr24_quiz_passes_when_stored_status_equals_expected(env, expected):
    """Quiz passes when the seed concept's stored status equals the judged one (right or wrong)."""

    def on_query(n):
        if n == 2:
            set_status("photosynthesis", expected)

    result = run_hooked(quiz_row(expected), FakeServer(), on_query)
    assert result["passed"] is True and result["reason"] == "ok"


def test_fr24_quiz_fails_when_status_differs(env):
    """Quiz fails with 'status is <stored>, expected <expected>' when the status differs."""

    def on_query(n):
        if n == 2:
            set_status("photosynthesis", "wrong")

    result = run_hooked(quiz_row("right"), FakeServer(), on_query)
    assert result["passed"] is False
    assert result["reason"] == "status is wrong, expected right"


def test_fr24_quiz_fails_when_status_still_new(env):
    """A status never updated stays 'new' and fails against right."""
    result = run_hooked(quiz_row("right"), FakeServer(), lambda n: None)
    assert result["passed"] is False
    assert result["reason"] == "status is new, expected right"


def test_fr24_quiz_fails_when_seed_concept_missing(env):
    """If the seed concept is gone after the turns, the quiz fails with 'seed concept missing'."""

    def on_query(n):
        con = sqlite3.connect(eval_config.DB_PATH)
        try:
            with con:
                con.execute("DELETE FROM concepts")
        finally:
            con.close()

    result = run_hooked(quiz_row(), FakeServer(), on_query)
    assert result["passed"] is False
    assert "seed concept missing" in result["reason"]


def test_fr24_quiz_http_failure_fails_with_http_reason(env):
    """A 500 on the answer turn fails the quiz with the http reason."""
    result = run_hooked(quiz_row(), FakeServer(status={2: 500}), lambda n: None)
    assert result["passed"] is False
    assert result["reason"].startswith("http 500")


# ---------- summary and report (T6: FR-19, FR-21, FR-23, FR-24) ----------


def case(row_id, group, passed=True, total_s=4.0, status=200) -> dict:
    return {
        "id": row_id,
        "group": group,
        "turns": [{"clip": row_id, "status": status}],
        "passed": passed,
        "reason": "ok" if passed else "answer lacks one of ['x']",
        "transcript": f"said {row_id}",
        "answer": f"answer {row_id}",
        "tools": ["web_search"] if group == "look" else [],
        "stt_s": 0.5,
        "llm_s": 2.0,
        "tts_s": 0.25,
        "total_s": total_s,
    }


def full_progress(**overrides) -> dict:
    """All five rows of data_v2() finished and passed; overrides replace a case by id."""
    progress = {
        "look01": case("look01", "look", total_s=4.0),
        "look02": case("look02", "look", total_s=6.0),
        "fu01": case("fu01", "followup"),
        "c01": case("c01", "concept"),
        "qz01": case("qz01", "quiz"),
    }
    progress.update(overrides)
    return progress


def test_fr19_targets_in_config():
    """Targets: Look >= 80%, follow-ups 80%, concepts 90%, quiz 80%, Look median <= 8 s."""
    assert eval_config.GROUP_TARGETS_V2 == {
        "look": 0.8,
        "followup": 0.8,
        "concept": 0.9,
        "quiz": 0.8,
    }
    assert eval_config.LOOK_MEDIAN_MAX_S == 8


def test_fr19_summarize_counts_passed_per_group():
    """summarize gives passed/total/finished/rate/target/met per group."""
    s = ev2.summarize(data_v2(), full_progress())
    assert set(s["groups"]) == {"look", "followup", "concept", "quiz"}
    look = s["groups"]["look"]
    assert (look["passed"], look["total"], look["finished"]) == (2, 2, 2)
    assert look["rate"] == 1.0 and look["target"] == 0.8 and look["met"] is True
    assert s["groups"]["quiz"]["total"] == 1


def test_fr19_summarize_look_below_target_not_met():
    """One of two Look cases passing (50%) is below 80%: not met, all_met false."""
    progress = full_progress(look02=case("look02", "look", passed=False))
    s = ev2.summarize(data_v2(), progress)
    look = s["groups"]["look"]
    assert look["passed"] == 1 and look["rate"] == 0.5 and look["met"] is False
    assert s["verdict"]["groups"] is False
    assert s["verdict"]["all_met"] is False


def test_fr23_summarize_unfinished_cases_count_as_not_passed():
    """Total comes from the question file: unfinished cases lower the rate and are not counted finished."""
    progress = full_progress()
    del progress["look02"]
    s = ev2.summarize(data_v2(), progress)
    look = s["groups"]["look"]
    assert (look["passed"], look["total"], look["finished"]) == (1, 2, 1)
    assert look["rate"] == 0.5 and look["met"] is False


def test_fr24_summarize_missing_groups_listed_and_incomplete():
    """A group with no finished case is listed in missing_groups; complete and all_met are false."""
    progress = full_progress()
    del progress["qz01"]
    s = ev2.summarize(data_v2(), progress)
    assert s["missing_groups"] == ["quiz"]
    assert s["verdict"]["complete"] is False
    assert s["verdict"]["all_met"] is False


def test_fr24_summarize_complete_run_has_no_missing_groups():
    """A full passing run: nothing missing, every verdict key true."""
    s = ev2.summarize(data_v2(), full_progress())
    assert s["missing_groups"] == []
    assert s["verdict"] == {
        "groups": True,
        "look_latency": True,
        "complete": True,
        "all_met": True,
    }


def test_fr21_summarize_look_latency_median_and_worst():
    """Look median and worst total seconds come from the finished Look cases only."""
    progress = full_progress(
        fu01=case("fu01", "followup", total_s=99.0),
        look01=case("look01", "look", total_s=3.0),
        look02=case("look02", "look", total_s=9.0),
    )
    lat = ev2.summarize(data_v2(), progress)["look_latency"]
    assert lat["median_total_s"] == pytest.approx(6.0)
    assert lat["worst_total_s"] == pytest.approx(9.0)


def test_fr21_summarize_look_median_over_limit_fails_verdict():
    """Look median above LOOK_MEDIAN_MAX_S fails look_latency and all_met; exactly 8 s passes."""
    slow = full_progress(
        look01=case("look01", "look", total_s=9.0),
        look02=case("look02", "look", total_s=10.0),
    )
    s = ev2.summarize(data_v2(), slow)
    assert s["verdict"]["look_latency"] is False
    assert s["verdict"]["all_met"] is False
    edge = full_progress(
        look01=case("look01", "look", total_s=8.0),
        look02=case("look02", "look", total_s=8.0),
    )
    assert ev2.summarize(data_v2(), edge)["verdict"]["look_latency"] is True


def test_fr21_summarize_no_look_cases_gives_zero_latency():
    """With no finished Look case the latency numbers are zero."""
    progress = {"c01": case("c01", "concept")}
    lat = ev2.summarize(data_v2(), progress)["look_latency"]
    assert lat["median_total_s"] == 0 and lat["worst_total_s"] == 0


def test_fr21_summarize_counts_errors_but_all_met_does_not_need_zero():
    """errors counts finished cases with a non-200 turn; they do not by themselves block all_met."""
    progress = full_progress(c01=case("c01", "concept", passed=True, status=500))
    s = ev2.summarize(data_v2(), progress)
    assert s["errors"] == 1
    assert s["verdict"]["all_met"] is True


def test_fr21_render_markdown_sections_and_targets():
    """Report has the heading, Targets section with per-group lines, Look latency, secrets and cases."""
    progress = full_progress(look02=case("look02", "look", passed=False))
    md = ev2.render_markdown(ev2.summarize(data_v2(), progress), [])
    assert md.startswith("# Eval report v2")
    assert "## Targets" in md and "## Cases" in md and "## Answers" in md
    assert "look: 1/2 passed" in md
    assert "NOT met" in md
    assert "followup: 1/1 passed" in md
    assert "(target <= 8 s)" in md
    assert "secrets: ok" in md
    assert "missing groups: none" in md
    for row_id in progress:
        assert row_id in md
    assert "answer lacks one of ['x']" in md
    assert "answer c01" in md


def test_fr21_render_markdown_lists_secret_problems():
    """Secret problems are printed instead of 'secrets: ok'."""
    md = ev2.render_markdown(
        ev2.summarize(data_v2(), full_progress()),
        ["GEMINI_API_KEY value found in logs"],
    )
    assert "GEMINI_API_KEY value found in logs" in md
    assert "secrets: ok" not in md


def test_fr24_render_markdown_partial_run_names_missing_groups():
    """A partial run says 'missing groups: look, quiz'."""
    progress = {
        "fu01": case("fu01", "followup"),
        "c01": case("c01", "concept"),
    }
    md = ev2.render_markdown(ev2.summarize(data_v2(), progress), [])
    assert "missing groups: look, quiz" in md


@pytest.fixture
def report_env(env, monkeypatch, tmp_path):
    results = tmp_path / "results"
    monkeypatch.setattr(eval_config, "RESULTS_DIR", results)

    class Stamp:
        def strftime(self, fmt):
            return "2026-10-17_1530"

    monkeypatch.setattr(run_eval, "now", lambda: Stamp())
    return results


def test_fr21_write_report_writes_md_and_json_with_stamp(report_env):
    """write_report creates <date_time>_v2.md and .json in RESULTS_DIR and returns the .md path."""
    progress = full_progress()
    summary = ev2.summarize(data_v2(), progress)
    path = ev2.write_report(summary, ["oops"], progress)
    assert path == report_env / "2026-10-17_1530_v2.md"
    assert path.read_text(encoding="utf-8").startswith("# Eval report v2")
    saved = json.loads((report_env / "2026-10-17_1530_v2.json").read_text("utf-8"))
    assert saved["secrets"] == ["oops"]
    assert saved["cases"] == progress
    assert saved["groups"]["look"]["passed"] == 2
    assert saved["verdict"]["all_met"] is True


def test_fr19_main_writes_report_and_prints_summary(
    main_env, report_env, monkeypatch, capsys
):
    """A full main run restores the DB, writes the report, and prints group lines, Look latency, targets and report path."""
    monkeypatch.setattr(ev2, "secrets_problems", list)
    assert ev2.main([]) == 0
    out = capsys.readouterr().out
    for name, total in (("look", 2), ("followup", 1), ("concept", 1), ("quiz", 1)):
        assert f"{name}: " in out and f"/{total} passed" in out
    assert "targets met: " in out
    assert "report: " in out and "_v2.md" in out
    assert (report_env / "2026-10-17_1530_v2.md").exists()
    assert (report_env / "2026-10-17_1530_v2.json").exists()
    assert counts(main_env["env"]) == (1, 1, 1)


def test_fr24_main_partial_group_run_reports_missing_groups(
    main_env, report_env, monkeypatch, capsys
):
    """Running only one group reports the other three as missing and targets met: no."""
    monkeypatch.setattr(ev2, "secrets_problems", list)
    assert ev2.main(["--group", "concept"]) == 0
    out = capsys.readouterr().out
    assert "missing groups: look, followup, quiz" in out
    assert "targets met: no" in out
    saved = json.loads((report_env / "2026-10-17_1530_v2.json").read_text("utf-8"))
    assert saved["missing_groups"] == ["look", "followup", "quiz"]
    assert set(saved["cases"]) == {"c01"}


def test_fr19_main_report_written_even_when_all_cases_already_finished(
    main_env, report_env, monkeypatch, capsys
):
    """If progress already holds every case, main runs none but still writes the report."""
    monkeypatch.setattr(ev2, "secrets_problems", list)
    ev2.save_progress(full_progress())
    assert ev2.main([]) == 0
    assert main_env["calls"] == []
    assert (report_env / "2026-10-17_1530_v2.md").exists()
    assert "targets met: yes" in capsys.readouterr().out


def test_fr21_main_report_includes_secret_problems(
    main_env, report_env, monkeypatch, capsys
):
    """Problems from secrets_problems appear in the report and the printed output."""
    monkeypatch.setattr(
        ev2, "secrets_problems", lambda: ["TAVILY_API_KEY value found in logs"]
    )
    ev2.main(["--group", "concept"])
    md = (report_env / "2026-10-17_1530_v2.md").read_text(encoding="utf-8")
    assert "TAVILY_API_KEY value found in logs" in md
