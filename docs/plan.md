# Plan: AI Assistant v1 Voice assistant

## M1 (v1): Server skeleton, config and logger | done
Goal: A FastAPI app with /health, settings in config, and a JSONL query logger · GitHub milestone: #1

| Task | FR | Files | Done when | Test | Issue | Done |
| --- | --- | --- | --- | --- | --- | --- |
| M1-T1 | FR-18 | requirements.txt, server/config.py, server/main.py, CLAUDE.md (+ server/__init__.py, tests/test_server.py) | GET /health returns 200 {"status": "ok", "model": "<model name>"}; main.py calls `uvicorn.run(app, host=config.HOST, port=config.PORT)` under `if __name__ == "__main__"` and the CLAUDE.md run command becomes `.venv\Scripts\python -m server.main` | pytest | #6 | [x] |
| M1-T2 | FR-17 | server/logger.py, server/config.py (+ tests/test_logger.py) | Writes one JSONL line with time, question, answer, per-stage timings, `searched`, tool calls (name, arguments, ok or error) and error; no API key or token ever appears in the log (the test sets a fake GEMINI_API_KEY and asserts it never appears in the line) | pytest | #5 | [x] |

Manual checks: the server binds to the configured host 127.0.0.1, so another device on the same Wi-Fi gets no answer on the port (FR-18).

## M2 (v1): Speech-to-text | done
Goal: Turn question audio into text with faster-whisper `small.en`, loaded once at startup · GitHub milestone: #2

| Task | FR | Files | Done when | Test | Issue | Done |
| --- | --- | --- | --- | --- | --- | --- |
| M2-T1 | FR-4 | requirements.txt, server/config.py, server/stt.py (+ tests/test_stt.py) | Turns a question WAV into text with faster-whisper `small.en`; `load()` builds the model once from config `STT_MODEL`, `STT_DEVICE` ("cuda") and `STT_COMPUTE_TYPE` ("float16"), so "cpu"/"int8" needs only a config change; `transcribe(wav)` passes the WAV bytes to the model and returns the segment texts joined into one string; tests use a fake model (no download, GPU or CUDA) | pytest | #8 | [x] |
| M2-T2 | FR-4 | server/main.py, server/stt.py, server/config.py (+ tests/test_server.py, tests/test_stt.py) | The FastAPI lifespan calls `stt.load()` once at startup, never per request; `/health` still returns 200; tests fake `stt.load`. After building the model, `load()` transcribes a short silent clip once as a warm-up and prints its time to stderr (`stt warm-up: <ms> ms`); the first transcription after startup takes ≤ 1 s; unit tests use a fake model only | pytest | #9 | [x] |

Manual checks: with the CUDA 12 toolkit and cuDNN 9 installed, transcribe one short spoken 16 kHz mono WAV with a one-off command against `stt`; the text matches what was said and the command prints how long one transcription takes (target ≤ 1 s, FR-4). The first run downloads the small.en model. "≥ 90% keep their meaning" is measured in M7. After M2-T2: start the server, see the `stt warm-up` line on stderr, then the first transcription after startup takes ≤ 1 s.

## M3 (v1): Gemini answers with Search | in progress
Goal: Spike Search + function calling with our key, then `llm.ask` with the system instruction, current time and the `searched` flag · GitHub milestone: #3

| Task | FR | Files | Done when | Test | Issue | Done |
| --- | --- | --- | --- | --- | --- | --- |
| M3-T1 | FR-5 | docs/plan.md (spike script runs from the scratchpad, never committed) | Following the current official docs ([tool combination](https://ai.google.dev/gemini-api/docs/generate-content/tool-combination), [Interactions API](https://ai.google.dev/gemini-api/docs/interactions-overview)), one request with our key combines `google_search` and one test function declaration in the documented way: first `generate_content` with `include_server_side_tool_invocations`, and if that fails, the Interactions API. It uses `LLM_MODEL` from config (gemini-3.8-flash); if search grounding isn't allowed for it on our free tier, it tries one other current Flash model listed in AI Studio before declaring the fallback. A live question returns grounded text, and the grounding metadata shows a search. A note-style command returns a function call. The key is read from .env and never printed or logged. Recorded below: the API and model that worked, the SDK version, the confirmed parameter names (timeout unit, thinking level, grounding metadata field), the time of the searched answer (budget 8 s), and pass or "use the web_search fallback". If the result changes how llm.py must call Gemini, propose a design.md update and adjust M3-T3 before building it | manual | #11 | [ ] |
| M3-T2 | FR-6 | requirements.txt (tzdata), server/config.py (`TIME_ZONE`, `HOME_CITY`), server/llm.py (+ tests/test_llm.py) | With the clock fixed at Fri 9 Oct 2026 14:00 IST, the system instruction contains that date, weekday and time in Asia/Kolkata, plus the home city from config. It also contains the design's rules: at most 2 short sentences under 40 words except lists, use Search for live info, turn relative times into exact ISO 8601 with offset, repeat actions back | pytest | #12 | [ ] |
| M3-T3 | FR-5 | requirements.txt (google-genai, python-dotenv), server/config.py (`GEMINI_API_KEY` from .env, `LLM_TIMEOUT_S` = 8, thinking level), server/llm.py (+ tests/test_llm.py) | `ask(question)` calls the Gemini 3 Flash model from config through `google-genai` with minimal thinking, an 8 s timeout per call, the API key from an environment variable, the `google_search` tool and the system instruction. It returns the answer text and `searched`, which is true when the response's grounding metadata shows a search. A timeout or API failure raises an error that names the `llm` stage. Tests use a fake client, so they need no network | pytest | #13 | [ ] |

Spike result (M3-T1): not run yet.

Notes: the five tool declarations, `VALIDATED` mode and the tool-call loop come in M5; `llm.ask` is wired into `/query` in M4. If the spike falls back to `web_search`, M3 is replanned.

Manual checks: after M3-T3, ask a live question with the real key (e.g. today's weather in the home city) using a one-off command against `llm`. The answer should be correct, `searched` true, under 40 words, and the call should take ≤ 8 s (FR-5). "≥ 80% of the general and live eval questions correct" and the "tomorrow at 5" → `due_at` check (FR-6) are measured in M7.

## M4 (v1): TTS and full /query pipeline with server errors | planned
Goal: Piper TTS at 16 kHz; /query runs STT → LLM → TTS with 400/500 errors and one log line per query · FRs: FR-11, FR-16, FR-17 (one line per query) · Tasks: not planned yet

## M5 (v1): Tools: notes and reminders | planned
Goal: SQLite store, the five tools, the tool-call loop, repeat-back answers and the reminder endpoints · FRs: FR-7, FR-8, FR-9, FR-10, FR-12, FR-13, FR-14 · Tasks: not planned yet

## M6 (v1): PC client | planned
Goal: Push-to-talk recording, status sounds, 20 s timeout and due-reminder polling · FRs: FR-1, FR-2, FR-3, FR-15 (Due reminders target) · Tasks: not planned yet

## M7 (v1): Evaluation and reliability | planned
Goal: Frozen questions.csv and run_eval.py; meet the correctness, latency, transcription, reliability and secrets targets · FRs: quality targets; settles how eval questions are spoken · Tasks: not planned yet
