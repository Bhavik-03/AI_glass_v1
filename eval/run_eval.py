import json
import sqlite3
import subprocess
import time
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
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
        print(
            f"{n:2}/{len(questions)} {result['id']} {result['status']} {result['wall_s']:.1f} s"
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
