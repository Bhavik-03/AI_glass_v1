import json
import re
import sqlite3
import subprocess
import time
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timedelta
from datetime import time as time_of_day
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from eval import config
from server import config as server_config


def _copy_db(src: Path, dest: Path) -> None:
    with (
        closing(sqlite3.connect(src)) as source,
        closing(sqlite3.connect(dest)) as target,
    ):
        source.backup(target)


def _restore() -> None:
    """Put the backed-up rows back and remove the marker."""
    backup = Path(config.MARKER_PATH.read_text(encoding="utf-8").strip())
    if not backup.exists():
        raise RuntimeError(f"backup named in {config.MARKER_PATH} is missing: {backup}")
    _copy_db(backup, config.DB_PATH)
    config.MARKER_PATH.unlink()


def begin() -> None:
    """Back up the DB, then clear notes and reminders so the run starts clean."""
    if config.MARKER_PATH.exists():  # a previous run crashed before end()
        _restore()
    config.CLIP_DIR.mkdir(parents=True, exist_ok=True)
    backup = (
        config.CLIP_DIR
        / f"backup-{datetime.now(ZoneInfo(server_config.TIMEZONE)):%Y%m%d-%H%M%S}.db"
    )
    _copy_db(config.DB_PATH, backup)
    config.MARKER_PATH.write_text(str(backup), encoding="utf-8")
    with closing(sqlite3.connect(config.DB_PATH)) as con, con:
        con.execute("DELETE FROM notes")
        con.execute("DELETE FROM reminders")


def end() -> None:
    if config.MARKER_PATH.exists():
        _restore()


def check_clips(questions: list[dict]) -> list[str]:
    return [
        q["id"] for q in questions if not (config.CLIP_DIR / f"{q['id']}.wav").exists()
    ]


def client_running(run: Callable = subprocess.run) -> bool:
    """True if a PC client process is running; it would acknowledge the eval's reminders."""
    script = (
        "Get-CimInstance Win32_Process | Where-Object "
        f"{{ $_.CommandLine -like '*{config.CLIENT_MODULE}*' -and $_.ProcessId -ne $PID }} "
        "| Select-Object -ExpandProperty ProcessId"
    )
    try:
        done = run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=config.PROCESS_LIST_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0 and bool(done.stdout.strip())


def gemini_calls(entry: dict | None) -> int:
    if entry is None:
        return server_config.MAX_TOOL_ROUNDS + 1
    return len(entry["tool_calls"]) + 1


def pace(
    elapsed_s: float, calls: int, sleep: Callable[[float], None] = time.sleep
) -> None:
    wait = config.SECONDS_PER_CALL * calls - elapsed_s
    if wait > 0:
        sleep(wait)


def log_offset() -> int:
    try:
        return config.LOG_PATH.stat().st_size
    except FileNotFoundError:
        return 0


def read_log_since(offset: int) -> list[dict]:
    try:
        with config.LOG_PATH.open("rb") as f:
            f.seek(offset)
            data = f.read().decode("utf-8")
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in data.splitlines() if line.strip()]


DAYS_AHEAD = {"tomorrow": 1, "day_after_tomorrow": 2}


def now() -> datetime:
    return datetime.now(ZoneInfo(server_config.TIMEZONE))


def snapshot_db() -> dict:
    """The notes and reminders as the server stored them."""
    with closing(sqlite3.connect(config.DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        notes = con.execute("SELECT id, text FROM notes ORDER BY id").fetchall()
        reminders = con.execute(
            "SELECT id, text, due_at, status FROM reminders ORDER BY id"
        ).fetchall()
    return {
        "notes": [dict(r) for r in notes],
        "reminders": [dict(r) for r in reminders],
    }


def expected_due(spec: dict, asked_at: datetime) -> tuple[datetime, int]:
    """The time a reminder should be due, resolved from when the question was asked."""
    if "in_minutes" in spec:
        return asked_at + timedelta(
            minutes=spec["in_minutes"]
        ), config.DUE_IN_TOLERANCE_S
    day, clock = spec["at"].split()
    date = asked_at.date() + timedelta(days=DAYS_AHEAD[day])
    due = datetime.combine(
        date, time_of_day.fromisoformat(clock), tzinfo=asked_at.tzinfo
    )
    return due, config.DUE_AT_TOLERANCE_S


def _has_word(text: str, word: str) -> bool:
    return (
        re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text, re.IGNORECASE) is not None
    )


def _contains_all(text: str, words: list[str]) -> bool:
    return all(w.lower() in text.lower() for w in words)


def _tool_failures(rule: dict, log: dict) -> list[str]:
    failures = []
    calls = log["tool_calls"]
    for tool in rule.get("tools", []):
        made = [c for c in calls if c["name"] == tool]
        if not made:
            failures.append(f"tool {tool} not called")
        elif not any(c["ok"] for c in made):
            failures.append(f"tool {tool} returned an error")
    if rule.get("searched") and not log["searched"]:
        failures.append("searched was false")
    return failures


def _answer_failures(rule: dict, answer: str) -> list[str]:
    failures = []
    for alternatives in rule.get("answer_all", []):
        if not any(_has_word(answer, a) for a in alternatives):
            failures.append(f"answer lacks one of {alternatives}")
    some = rule.get("answer_some")
    if some:
        found = [w for w in some["words"] if _has_word(answer, w)]
        if len(found) < some["min"]:
            failures.append(f"answer_some: {len(found)} of {some['min']} words {found}")
    fact = rule.get("answer_fact")
    if fact and not re.search(fact, answer, re.IGNORECASE):
        failures.append(f"answer_fact: no match for {fact}")
    return failures


def _reminder_added_failure(
    spec: dict, reminders: list[dict], asked_at: datetime
) -> str | None:
    found = [r for r in reminders if _contains_all(r["text"], spec["words"])]
    if not found:
        return f"reminder_added: no reminder with {spec['words']}"
    due, tolerance = expected_due(spec["due"], asked_at)
    for r in found:
        if (
            abs((datetime.fromisoformat(r["due_at"]) - due).total_seconds())
            <= tolerance
        ):
            return None
    return f"reminder_added: due_at {found[0]['due_at']} is not near {due.isoformat()}"


def _db_failures(rule: dict, db: dict, asked_at: datetime) -> list[str]:
    failures = []
    notes, reminders = db["notes"], db["reminders"]
    words = rule.get("note_added")
    if words and not any(_contains_all(n["text"], words) for n in notes):
        failures.append(f"note_added: no note with {words}")
    if "notes_total" in rule and len(notes) != rule["notes_total"]:
        failures.append(
            f"notes_total: {len(notes)} stored, expected {rule['notes_total']}"
        )
    if "reminder_added" in rule:
        failure = _reminder_added_failure(rule["reminder_added"], reminders, asked_at)
        if failure:
            failures.append(failure)
    words = rule.get("reminder_cancelled")
    if words and not any(
        r["status"] == "cancelled" and _contains_all(r["text"], words)
        for r in reminders
    ):
        failures.append(f"reminder_cancelled: no cancelled reminder with {words}")
    if "reminders_pending" in rule:
        pending = sum(r["status"] == "pending" for r in reminders)
        if pending != rule["reminders_pending"]:
            failures.append(
                f"reminders_pending: {pending} pending, expected {rule['reminders_pending']}"
            )
    return failures


def grade(question: dict, result: dict) -> tuple[bool, str]:
    """Check one result against the question's pass rule; the reason lists every failed check."""
    if result["status"] != 200:
        return False, f"http {result['status']}: {result['error']}"
    log = result["log"]
    if log is None:
        return False, "no log line"
    rule = question.get("pass", {})
    asked_at = datetime.fromisoformat(result["asked_at"])
    failures = (
        _tool_failures(rule, log)
        + _answer_failures(rule, log["answer"])
        + _db_failures(rule, result["db"], asked_at)
    )
    return (not failures, "; ".join(failures) or "ok")


def run_one(
    client: httpx.Client, question: dict, clock: Callable[[], float] = time.perf_counter
) -> dict:
    wav = (config.CLIP_DIR / f"{question['id']}.wav").read_bytes()
    result = {
        "id": question["id"],
        "group": question["group"],
        "status": None,
        "error": None,
        "wall_s": 0.0,
        "log": None,
        "asked_at": now().isoformat(),
    }
    offset = log_offset()
    start = clock()
    try:
        response = client.post("/query", files={"audio": ("q.wav", wav, "audio/wav")})
    except httpx.HTTPError as e:
        result["error"] = str(e) or type(e).__name__
    else:
        result["status"] = response.status_code
        if response.status_code != 200:
            result["error"] = _error_text(response)
    result["wall_s"] = clock() - start
    lines = read_log_since(offset)
    result["log"] = lines[-1] if lines else None
    result["db"] = snapshot_db()
    result["passed"], result["reason"] = grade(question, result)
    return result


def _error_text(response: httpx.Response) -> str:
    try:
        return response.json()["error"]
    except (ValueError, KeyError, TypeError):
        return response.text


def replay(
    questions: list[dict],
    client: httpx.Client,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.perf_counter,
) -> list[dict]:
    results = []
    for n, question in enumerate(questions, 1):
        result = run_one(client, question, clock)
        results.append(result)
        verdict = "PASS" if result["passed"] else f"FAIL {result['reason']}"
        print(
            f"{n:2}/{len(questions)} {result['id']} {result['status']} "
            f"{result['wall_s']:.1f} s {verdict}"
        )
        pace(result["wall_s"], gemini_calls(result["log"]), sleep)
    return results


def _server_ok(client: httpx.Client) -> bool:
    try:
        return client.get("/health").status_code == 200
    except httpx.HTTPError:
        return False


def main() -> int:
    questions = json.loads(config.QUESTIONS_PATH.read_text(encoding="utf-8"))
    with httpx.Client(
        base_url=config.SERVER_URL, timeout=config.QUERY_TIMEOUT_S
    ) as client:
        if not _server_ok(client):
            print(
                f"The server at {config.SERVER_URL} is not answering /health. Start it first."
            )
            return 1
        missing = check_clips(questions)
        if missing:
            print(f"Missing clips: {', '.join(missing)}. Run: python -m eval.record")
            return 1
        if client_running():
            print(
                "Warning: the PC client is running; it may acknowledge eval reminders."
            )
        try:
            begin()
            replay(questions, client)
        finally:
            end()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
