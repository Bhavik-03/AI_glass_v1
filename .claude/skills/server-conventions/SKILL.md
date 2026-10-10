---
name: server-conventions
description: FastAPI and pytest conventions for the ai-glasses server. Use when writing or editing server/ or tests/, or writing tests for an FR.
user-invocable: false
paths:
  - "server/**"
  - "tests/**"
---
# Server conventions (v1 voice assistant)

## Stage modules (server/stt.py, llm.py, tts.py, logger.py)
- Signatures are fixed; main.py and tests depend on them:
  - `stt.load() -> None`, `stt.transcribe(wav: bytes) -> str`
  - `llm.ask(question: str, now: datetime) -> tuple[str, bool, list[dict]]` → (answer, searched, tool_calls); each tool call is `{"name", "args", "ok"}`
  - `tts.load() -> None`, `tts.synthesize(text: str) -> bytes` (16 kHz mono 16-bit WAV)
  - `logger.log_query(record: dict) -> None`
- `load()` keeps the model in a module-level variable; it's called once from the FastAPI lifespan in main.py, never on import.
- Stages raise normal exceptions with a clear message; they don't know their stage name or HTTP codes.
- `logger.log_query` never raises: catch, print to stderr, continue.
- Settings come from `from server import config`. config.py loads `.env` with python-dotenv and reads `os.getenv("GEMINI_API_KEY", "")`; llm raises if it's empty. Never print or log the key or any token.

## tools.py and store.py (serve the llm stage and the reminder endpoints)
- `tools.DECLARATIONS`: the function declarations for the tools listed in spec.md "Tool functions".
  In M3 only web_search is implemented; the notes and reminder tools arrive in M5.
- `tools.run(name: str, args: dict, now: datetime) -> dict` runs one call against `store` and never raises: unknown names, bad arguments and rule failures (a `due_at` in the past, an unknown or non-pending id) return `{"error": "<reason>"}`.
- `tools.reminder_text(reminder: dict, now: datetime) -> str` builds "Reminder, 5 pm: …" / "Missed reminder, …" (FR-13), using `config.MISSED_AFTER_S`.
- `store.init() -> None` creates the tables in `config.DB_PATH`; called once from the lifespan. Store functions take and return plain dicts with ISO 8601 times; they hold no business rules.
- Use stdlib `sqlite3` with parameterised queries only; open a connection per call (FastAPI runs `def` handlers in a thread pool).

## llm.py
- The system instruction is a constant in llm.py, filled per request with the current date, weekday and time (`now`) and `config.HOME_CITY`; design.md lists its rules.
- Every request carries `tools.DECLARATIONS` as plain function declarations, with no built-in tools. Web search is a normal tool, `web_search(query)`: declared in tools.py, run through search.py (Tavily). Only the search query goes to Tavily, never notes, reminders or memory.
- Settings: `ThinkingConfig(thinking_level="MINIMAL")`; `config.LLM_TIMEOUT_S = 10`, passed in ms through `HttpOptions(timeout=...)` (the API rejects less than 10 s); function calling in `VALIDATED` mode.
- Tool loop: run each function call through tools.py, send the results back, repeat until Gemini returns text; stop after `config.MAX_TOOL_ROUNDS` (3) and raise `too many tool rounds`.
- Deadline: the LLM stage has an overall deadline (`config.LLM_DEADLINE_S`) so STT + LLM + TTS stays inside the client's 20 s timeout. A Gemini or search call starts only if its full timeout fits in the time left, else raise `deadline exceeded`.
- thought_signature: when the model returns a function call, send its previous content back unchanged, including each part's `id` and `thought_signature`, together with the function response.
- `searched` is True when `web_search` ran and returned results.
- google-genai details (timeout units, thinking setting, function-call parts) change between versions: check the current SDK docs before writing llm.py.

## main.py (the only file that knows the stage order)
- `def now() -> datetime` returns the current time in `config.TIMEZONE` (`zoneinfo`); handlers call it once per request and pass it on, tests monkeypatch it.
- Handlers are `def`, not `async def`: whisper, Piper and sqlite block, and FastAPI runs plain `def` handlers in a thread pool.
- Upload: `audio: UploadFile | None = File(None)`. Audio is required by the contract but declared optional, so a missing file gives 400 `{"error": ...}` instead of FastAPI's 422 `{"detail": ...}`.
- Errors: `JSONResponse(status_code=..., content={"error": ...})`. Never `HTTPException` (it returns `{"detail": ...}`).
- Validate audio before any stage runs, else 400: present; opens with stdlib `wave`; 1 channel, 16000 Hz, 2-byte samples, > 0 frames.
- Run every `/query` stage through one helper:
```python
def run_stage(name: str, timings: dict, fn, *args):
    t0 = time.perf_counter()
    try:
        return fn(*args)
    except Exception as e:
        raise StageFailed(name, e) from e     # caught in query() → 500 {"error": "<name>: <reason>"}
    finally:
        timings[name] = round((time.perf_counter() - t0) * 1000)   # ms, even on failure
```
- Log once per `/query` in a `finally:` block, success or failure: question, answer, timings_ms, searched, tool_calls, error, failed stage.
- Success: `Response(content=wav, media_type="audio/wav")`. Nothing due: `Response(status_code=204)`. Unknown reminder: 404 `{"error": "reminder not found"}`. `/health`: `{"status": "ok", "model": config.LLM_MODEL}`.

## Tests (tests/)
- pytest + FastAPI `TestClient`; shared fixtures in `tests/conftest.py`.
- Use `TestClient(app)`, not `with TestClient(app)`: the `with` form runs the lifespan and loads whisper and Piper. A fixture points `config.DB_PATH` at `tmp_path` and calls `store.init()`.
- Fake each stage in a fixture with `monkeypatch.setattr` (e.g. `server.stt.transcribe`); fake llm returns `("<answer>", False, [])`. Fix the clock by monkeypatching `server.main.now`. No network, GPU or model files in pytest.
- Test the tool-call loop with a fake Gemini client that returns a function call, then text; never call the real API.
- Build inputs in code, never commit binaries: WAV via `wave` (1 s of silence, 16 kHz mono 16-bit).
- One test per software-testable acceptance criterion: `test_fr<N>_<behaviour>`, with the criterion as the docstring.
- Every error-path test checks both the status code and the exact JSON shape.
- Hardware or human criteria (clear speech, audible, heard within 10 s) are never faked; plan.md lists them as manual checks.
