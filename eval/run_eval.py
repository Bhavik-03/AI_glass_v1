import json
import re
import sqlite3
import statistics
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


UNIT_WORDS = (
    ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
    + ("ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen")
    + ("seventeen", "eighteen", "nineteen")
)
TEN_WORDS = (
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
)
UNITS = {w: i for i, w in enumerate(UNIT_WORDS)}
TENS = {w: 10 * i for i, w in enumerate(TEN_WORDS, 2)}
STAGES = ("stt", "llm", "tts")
KEY_NAMES = ("GEMINI_API_KEY", "TAVILY_API_KEY")


def normalize(text: str) -> str:
    """Lowercase, no punctuation, number words as digits, so "five" equals "5"."""
    no_apostrophes = re.sub(r"['’]", "", text.lower())
    words = re.sub(r"[^\w\s]|_", " ", no_apostrophes).split()
    out, i = [], 0
    while i < len(words):
        word = words[i]
        if word in TENS:
            unit = UNITS.get(words[i + 1]) if i + 1 < len(words) else None
            if unit:  # "twenty one"; zero is not a unit
                out.append(str(TENS[word] + unit))
                i += 1
            else:
                out.append(str(TENS[word]))
        else:
            out.append(str(UNITS[word]) if word in UNITS else word)
        i += 1
    return " ".join(out)


def transcript_match(expected: str, heard: str | None) -> bool:
    return heard is not None and normalize(expected) == normalize(heard)


def timings_s(entry: dict | None) -> dict:
    ms = entry["timings_ms"] if entry else {}
    seconds = {stage: ms.get(stage, 0) / 1000 for stage in STAGES}
    return {**seconds, "total": sum(seconds.values())}


def _row(question: dict, result: dict) -> dict:
    log = result["log"]
    t = timings_s(log)
    heard = log["question"] if log else None
    return {
        "id": result["id"],
        "group": result["group"],
        "spoken": question["spoken"],
        "expected_transcript": question["expected_transcript"],
        "heard": heard,
        "transcript_ok": transcript_match(question["expected_transcript"], heard),
        "answer": log["answer"] if log else "",
        "tools": [c["name"] for c in log["tool_calls"]] if log else [],
        "searched": log["searched"] if log else False,
        "stt_s": t["stt"],
        "llm_s": t["llm"],
        "tts_s": t["tts"],
        "total_s": t["total"] if log else result["wall_s"],
        "wall_s": result["wall_s"],
        "status": result["status"],
        "passed": result["passed"],
        "reason": result["reason"],
    }


def summarize(questions: list[dict], results: list[dict]) -> dict:
    rows = [_row(q, r) for q, r in zip(questions, results)]
    groups: dict[str, dict] = {}
    for row in rows:
        g = groups.setdefault(row["group"], {"passed": 0, "total": 0})
        g["total"] += 1
        g["passed"] += row["passed"]
    for g in groups.values():
        g["rate"] = g["passed"] / g["total"]
    matched = sum(row["transcript_ok"] for row in rows)
    transcription = {
        "matched": matched,
        "total": len(rows),
        "rate": matched / len(rows),
    }
    totals = [row["total_s"] for row in rows]
    latency = {
        "median_total_s": statistics.median(totals),
        "worst_total_s": max(totals),
    }
    errors = sum(row["status"] != 200 for row in rows)
    verdict = {
        "groups": all(g["rate"] >= config.GROUP_PASS_MIN for g in groups.values()),
        "latency": latency["median_total_s"] <= config.MEDIAN_TOTAL_MAX_S,
        "no_errors": errors == 0,
        "transcription": transcription["rate"] >= config.TRANSCRIPTION_MIN,
    }
    verdict["all_met"] = all(verdict.values())
    return {
        "rows": rows,
        "groups": groups,
        "transcription": transcription,
        "latency": latency,
        "errors": errors,
        "verdict": verdict,
    }


def secrets_problems(run: Callable = subprocess.run) -> list[str]:
    """Key values found in the logs, or secret files tracked by git; never the key itself."""
    problems = []
    log_text = ""
    if config.LOG_PATH.exists():
        log_text = config.LOG_PATH.read_text(encoding="utf-8")
    for name in KEY_NAMES:
        value = getattr(server_config, name)
        if value and value in log_text:
            problems.append(f"{name} value found in logs")
    try:
        done = run(
            ["git", "ls-files"],
            capture_output=True,
            text=True,
            timeout=config.PROCESS_LIST_TIMEOUT_S,
            cwd=config.ROOT,
        )
    except (OSError, subprocess.TimeoutExpired):
        done = None
    if done is None or done.returncode != 0:
        return [*problems, "git ls-files failed"]
    for path in done.stdout.splitlines():
        if path == ".env" or path.startswith("data/") or path.endswith(".db"):
            problems.append(f"secret file tracked by git: {path}")
    return problems


def _met(ok: bool) -> str:
    return "met" if ok else "NOT met"


def render_markdown(summary: dict, secrets: list[str]) -> str:
    v, lat, tr = summary["verdict"], summary["latency"], summary["transcription"]
    lines = ["# Eval report", "", "## Targets", ""]
    for name, g in summary["groups"].items():
        lines.append(f"- {name}: {g['passed']}/{g['total']} passed ({g['rate']:.0%})")
    lines += [
        f"- every group >= {config.GROUP_PASS_MIN:.0%}: {_met(v['groups'])}",
        (
            f"- median total {lat['median_total_s']:.1f} s, "
            f"worst {lat['worst_total_s']:.1f} s "
            f"(target <= {config.MEDIAN_TOTAL_MAX_S} s): {_met(v['latency'])}"
        ),
        f"- errors (non-200): {summary['errors']}: {_met(v['no_errors'])}",
        (
            f"- transcription {tr['matched']}/{tr['total']} ({tr['rate']:.0%}, "
            f"target >= {config.TRANSCRIPTION_MIN:.0%}): {_met(v['transcription'])}"
        ),
        f"- secrets: {'; '.join(secrets) if secrets else 'ok'}",
        "",
        "## Questions",
        "",
        "| id | group | result | transcript | tools | stt s | llm s | tts s | total s | reason |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in summary["rows"]:
        lines.append(
            f"| {r['id']} | {r['group']} | {'pass' if r['passed'] else 'FAIL'} "
            f"| {'ok' if r['transcript_ok'] else 'differs'} | {', '.join(r['tools'])} "
            f"| {r['stt_s']:.1f} | {r['llm_s']:.1f} | {r['tts_s']:.1f} "
            f"| {r['total_s']:.1f} | {r['reason']} |"
        )
    lines += ["", "## Transcript differences", ""]
    lines += [
        f"- {r['id']}: expected `{r['expected_transcript']}`, heard `{r['heard']}`"
        for r in summary["rows"]
        if not r["transcript_ok"]
    ]
    lines += ["", "## Answers", ""]
    lines += [f"- {r['id']}: {r['answer']}" for r in summary["rows"]]
    return "\n".join(lines) + "\n"


def write_report(summary: dict, secrets: list[str]) -> Path:
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = now().strftime("%Y-%m-%d_%H%M")
    md_path = config.RESULTS_DIR / f"{stem}.md"
    md_path.write_text(render_markdown(summary, secrets), encoding="utf-8")
    data = {**summary, "secrets": secrets}
    (config.RESULTS_DIR / f"{stem}.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return md_path


def print_summary(summary: dict, secrets: list[str], report: Path) -> None:
    for name, g in summary["groups"].items():
        print(f"{name}: {g['passed']}/{g['total']} passed")
    tr, lat = summary["transcription"], summary["latency"]
    print(f"transcription: {tr['matched']}/{tr['total']}")
    print(
        f"latency: median {lat['median_total_s']:.1f} s, worst {lat['worst_total_s']:.1f} s"
    )
    print(f"errors: {summary['errors']}")
    print(f"secrets: {'; '.join(secrets) if secrets else 'ok'}")
    print(f"targets met: {'yes' if summary['verdict']['all_met'] else 'no'}")
    print(f"report: {report}")


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
            results = replay(questions, client)
        finally:
            end()
    summary = summarize(questions, results)
    secrets = secrets_problems()
    print_summary(summary, secrets, write_report(summary, secrets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
