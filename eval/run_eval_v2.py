import argparse
import json
import sqlite3
import time
from collections.abc import Callable, Sequence
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from eval import config
from eval.record import v2_items
from eval.run_eval import (
    _answer_failures,
    _copy_db,
    _error_text,
    _server_ok,
    client_running,
    gemini_calls,
    log_offset,
    pace,
    read_log_since,
    timings_s,
)
from server import config as server_config


def _restore() -> None:
    """Put the backed-up rows back and remove the marker."""
    backup = Path(config.MARKER_PATH_V2.read_text(encoding="utf-8").strip())
    if not backup.exists():
        raise RuntimeError(
            f"backup named in {config.MARKER_PATH_V2} is missing: {backup}"
        )
    _copy_db(backup, config.DB_PATH)
    config.MARKER_PATH_V2.unlink()


def begin() -> None:
    """Back up the DB, then clear notes, reminders and concepts so the run starts clean."""
    if config.MARKER_PATH_V2.exists():  # a previous run crashed before end()
        _restore()
    config.CLIP_DIR_V2.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo(server_config.TIMEZONE))
    backup = config.CLIP_DIR_V2 / f"backup-{stamp:%Y%m%d-%H%M%S}.db"
    _copy_db(config.DB_PATH, backup)
    config.MARKER_PATH_V2.write_text(str(backup), encoding="utf-8")
    with closing(sqlite3.connect(config.DB_PATH)) as con, con:
        for table in ("notes", "reminders", "concepts"):
            con.execute(f"DELETE FROM {table}")


def end() -> None:
    if config.MARKER_PATH_V2.exists():
        _restore()


def check_files(data: dict) -> list[str]:
    """Names of the clips and screenshots that are not saved yet."""
    missing = [
        f"{item['id']}.wav"
        for item in v2_items(data)
        if not (config.CLIP_DIR_V2 / f"{item['id']}.wav").exists()
    ]
    missing += [
        row["screenshot"]
        for row in data["rows"]
        if row["group"] == "look"
        and not (config.SCREENSHOT_DIR_V2 / row["screenshot"]).exists()
    ]
    return missing


def load_progress() -> dict:
    try:
        return json.loads(config.PROGRESS_PATH_V2.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def save_progress(progress: dict) -> None:
    config.PROGRESS_PATH_V2.parent.mkdir(parents=True, exist_ok=True)
    config.PROGRESS_PATH_V2.write_text(
        json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def clear_progress() -> None:
    config.PROGRESS_PATH_V2.unlink(missing_ok=True)


def clip_ids(row: dict) -> list[str]:
    if row["group"] == "followup":
        return [row["id"], f"{row['id']}_2"]
    if row["group"] == "quiz":
        return ["quiz_start", row["id"]]
    return [row["id"]]


def select(data: dict, group: str | None) -> list[dict]:
    return [row for row in data["rows"] if group is None or row["group"] == group]


def _turn(
    client: httpx.Client,
    clip: str,
    image: bytes | None,
    clock: Callable[[], float],
) -> dict:
    files = {
        "audio": (
            "q.wav",
            (config.CLIP_DIR_V2 / f"{clip}.wav").read_bytes(),
            "audio/wav",
        )
    }
    if image is not None:
        files["image"] = ("s.jpg", image, "image/jpeg")
    turn = {"clip": clip, "status": None, "error": None, "wall_s": 0.0, "log": None}
    offset = log_offset()
    start = clock()
    try:
        response = client.post("/query", files=files)
    except httpx.HTTPError as e:
        turn["error"] = str(e) or type(e).__name__
    else:
        turn["status"] = response.status_code
        if response.status_code != 200:
            turn["error"] = _error_text(response)
    turn["wall_s"] = clock() - start
    lines = read_log_since(offset)
    turn["log"] = lines[-1] if lines else None
    return turn


def _concept_names() -> list[str]:
    with closing(sqlite3.connect(config.DB_PATH)) as con:
        return [row[0] for row in con.execute("SELECT name FROM concepts ORDER BY id")]


def _concept_status(name: str) -> str | None:
    with closing(sqlite3.connect(config.DB_PATH)) as con:
        row = con.execute(
            "SELECT status FROM concepts WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
    return row[0] if row else None


def _seed_concept(seed: dict) -> None:
    """Make the seed the only concept, status new, so the quiz asks exactly it."""
    asked = datetime.now(ZoneInfo(server_config.TIMEZONE)).isoformat(timespec="seconds")
    with closing(sqlite3.connect(config.DB_PATH)) as con, con:
        con.execute("DELETE FROM concepts")
        con.execute(
            "INSERT INTO concepts (name, summary, first_asked, last_asked, status)"
            " VALUES (?, ?, ?, ?, 'new')",
            (seed["name"], seed.get("summary", ""), asked, asked),
        )


def _concept_failures(row: dict, before: list[str], log: dict) -> list[str]:
    after = _concept_names()
    failures = []
    if len({name.lower() for name in after}) != len(after):
        failures.append("duplicate concept name")
    added = len(after) - len(before)
    if row["pass"]["concept_added"]:
        if added != 1:
            failures.append("concept not added")
        if log["concept"] is None:
            failures.append("log concept is None")
    else:
        if added != 0:
            failures.append("concept added unexpectedly")
        if log["concept"] is not None:
            failures.append(f"log concept is {log['concept']} but none expected")
    return failures


def _quiz_failures(row: dict) -> list[str]:
    stored = _concept_status(row["seed"]["name"])
    if stored is None:
        return ["seed concept missing"]
    expected = row["pass"]["status"]
    return [] if stored == expected else [f"status is {stored}, expected {expected}"]


def _grade(row: dict, turns: list[dict], before: list[str]) -> tuple[bool, str]:
    for turn in turns:
        if turn["status"] != 200:
            return False, f"http {turn['status']}: {turn['error']}"
        if turn["log"] is None:
            return False, "no log line"
    log = turns[-1]["log"]
    failures = _answer_failures(row.get("pass", {}), log["answer"])
    if row["group"] == "look" and not log["image_sent"]:
        failures.append("image_sent was false")
    if row["group"] == "followup" and not log["session_continued"]:
        failures.append("session was not continued")
    if row["group"] == "concept" and "concept_added" in row.get("pass", {}):
        failures += _concept_failures(row, before, log)
    if row["group"] == "quiz" and "seed" in row and "status" in row.get("pass", {}):
        failures += _quiz_failures(row)
    return (not failures, "; ".join(failures) or "ok")


def _last_turn_fields(turn: dict) -> dict:
    """Transcript, answer, tools and stage seconds of the graded turn."""
    log = turn["log"]
    seconds = timings_s(log)
    return {
        "transcript": log["question"] if log else None,
        "answer": log["answer"] if log else "",
        "tools": [c["name"] for c in log["tool_calls"]] if log else [],
        "stt_s": seconds["stt"],
        "llm_s": seconds["llm"],
        "tts_s": seconds["tts"],
        "total_s": seconds["total"] if log else turn["wall_s"],
    }


def run_case(
    client: httpx.Client,
    row: dict,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.perf_counter,
) -> dict:
    """Run one case in a fresh session; the turns of a follow-up case share it (FR-22)."""
    if row["group"] == "quiz" and "seed" in row:
        _seed_concept(row["seed"])
    before = _concept_names()
    client.post("/session/reset").raise_for_status()
    image = None
    if row["group"] == "look":
        image = (config.SCREENSHOT_DIR_V2 / row["screenshot"]).read_bytes()
    turns = []
    for clip in clip_ids(row):
        turn = _turn(client, clip, image, clock)
        turns.append(turn)
        pace(turn["wall_s"], gemini_calls(turn["log"]), sleep)
        if turn["status"] != 200:
            break
    passed, reason = _grade(row, turns, before)
    return {
        "id": row["id"],
        "group": row["group"],
        "turns": turns,
        "passed": passed,
        "reason": reason,
        **_last_turn_fields(turns[-1]),
    }


def main(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=config.GROUPS_V2)
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args(argv)
    data = json.loads(config.QUESTIONS_V2_PATH.read_text(encoding="utf-8"))
    rows = select(data, args.group)
    with httpx.Client(
        base_url=config.SERVER_URL, timeout=config.QUERY_TIMEOUT_S
    ) as client:
        if not _server_ok(client):
            print(
                f"The server at {config.SERVER_URL} is not answering /health. Start it first."
            )
            return 1
        missing = check_files({**data, "rows": rows})
        if missing:
            print(
                f"Missing files: {', '.join(missing)}. Run: python -m eval.record --set v2"
            )
            return 1
        if client_running():
            print(
                "Warning: the PC client is running; it may acknowledge eval reminders."
            )
        if args.fresh:
            clear_progress()
        progress = load_progress()
        todo = [row for row in rows if row["id"] not in progress]
        try:
            begin()
            for n, row in enumerate(todo, 1):
                result = run_case(client, row)
                progress[row["id"]] = result
                save_progress(progress)
                verdict = "PASS" if result["passed"] else f"FAIL {result['reason']}"
                print(f"{n:2}/{len(todo)} {row['id']} {verdict}")
        finally:
            end()
    print(f"{len(progress)} of {len(data['rows'])} cases finished.")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
