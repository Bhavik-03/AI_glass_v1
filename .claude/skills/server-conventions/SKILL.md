---
name: server-conventions
description: FastAPI and pytest conventions for the ai-glasses server. Use when writing or editing server/ or tests/, or writing tests for an FR.
user-invocable: false
paths:
  - "server/**"
  - "tests/**"
---
# Server conventions

## Stage modules (server/stt.py, vlm.py, tts.py, logger.py)
- Signatures are fixed; main.py and tests depend on them:
  - `stt.load() -> None`, `stt.transcribe(wav: bytes) -> str`
  - `vlm.ask(question: str, jpeg: bytes | None) -> tuple[str, bool]` → (answer, searched)
  - `tts.load() -> None`, `tts.synthesize(text: str) -> bytes` (16 kHz mono 16-bit WAV)
  - `logger.log_query(record: dict, jpeg: bytes | None) -> None`
- `load()` keeps the model in a module-level variable; it's called once from the FastAPI lifespan in main.py, never on import.
- Stages raise normal exceptions with a clear message; they don't know their stage name or HTTP codes.
- `logger.log_query` never raises: catch, print to stderr, continue. It saves the photo only when `jpeg` is not None.
- Settings come from `from server import config`. config.py loads `.env` with python-dotenv and reads `os.getenv("GEMINI_API_KEY", "")`; vlm raises if it's empty. Never print or log the key.

## vlm.py
- The system instruction is a constant in vlm.py (design.md puts it there): at most 2 short sentences; use the photo only when the question is about what the user sees; search when live information is needed; home city from `config.HOME_CITY`.
- Google Search grounding on every request; Gemini decides when to search. `searched` is True when the response's grounding metadata shows a search.
- Add the photo part only when `jpeg` is not None.
- google-genai details (search tool, grounding metadata, timeout units, thinking setting) change between versions: check the current SDK docs before writing vlm.py.

## main.py (the only file that knows the stage order)
- `def query(...)`, not `async def`: whisper and Piper block, and FastAPI runs plain `def` handlers in a thread pool.
- Uploads: `audio: UploadFile | None = File(None)`, `image: UploadFile | None = File(None)`. Audio is required by the contract but declared optional, so a missing file gives 400 `{"error": ...}` instead of FastAPI's 422 `{"detail": ...}`.
- Errors: `JSONResponse(status_code=..., content={"error": ...})`. Never `HTTPException` (it returns `{"detail": ...}`).
- Validate before any stage runs, else 400:
  - audio: present; opens with stdlib `wave`; 1 channel, 16000 Hz, 2-byte samples, > 0 frames
  - image: optional; if the field is sent, it must be non-empty and start with `b"\xff\xd8\xff"`
- Run every stage through one helper:
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
- Log once per request in a `finally:` block, success or failure: question, answer, timings_ms, photo_sent, searched, error, failed stage.
- Success: `Response(content=wav, media_type="audio/wav")`. `/health`: `{"status": "ok", "model": config.VLM_MODEL}`.

## Tests (tests/)
- pytest + FastAPI `TestClient`; shared fixtures in `tests/conftest.py`.
- Use `TestClient(app)`, not `with TestClient(app)`: the `with` form runs the lifespan and loads whisper and Piper.
- Fake each stage in a fixture with `monkeypatch.setattr` (e.g. `server.stt.transcribe`); fake vlm returns `("<answer>", False)`. No network, GPU or model files in pytest.
- Cover both paths: Look (audio + image) and Ask (audio only: vlm gets `jpeg=None`, log says no photo).
- Build inputs in code, never commit binaries: WAV via `wave` (1 s of silence, 16 kHz mono 16-bit); JPEG as `b"\xff\xd8\xff\xe0" + b"\x00" * 100`.
- One test per software-testable acceptance criterion: `test_fr<N>_<behaviour>`, with the criterion as the docstring.
- Every error-path test checks both the status code and the exact JSON shape.
- Hardware or human criteria (20/20 sharp photos, audible in a lab) are never faked; plan.md lists them as manual checks.
