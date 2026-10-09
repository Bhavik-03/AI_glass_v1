# Plan: AI Assistant v1 Voice assistant

## M1 (v1): Server skeleton, config and logger | done
Goal: A FastAPI app with /health, settings in config, and a JSONL query logger · GitHub milestone: #1

| Task | FR | Files | Done when | Test | Issue | Done |
| --- | --- | --- | --- | --- | --- | --- |
| M1-T1 | FR-18 | requirements.txt, server/config.py, server/main.py, CLAUDE.md (+ server/__init__.py, tests/test_server.py) | GET /health returns 200 {"status": "ok", "model": "<model name>"}; main.py calls `uvicorn.run(app, host=config.HOST, port=config.PORT)` under `if __name__ == "__main__"` and the CLAUDE.md run command becomes `.venv\Scripts\python -m server.main` | pytest | #6 | [x] |
| M1-T2 | FR-17 | server/logger.py, server/config.py (+ tests/test_logger.py) | Writes one JSONL line with time, question, answer, per-stage timings, `searched`, tool calls (name, arguments, ok or error) and error; no API key or token ever appears in the log (the test sets a fake GEMINI_API_KEY and asserts it never appears in the line) | pytest | #5 | [x] |

Manual checks: the server binds to the configured host 127.0.0.1, so another device on the same Wi-Fi gets no answer on the port (FR-18).

## M2 (v1): Speech-to-text | in progress
Goal: Turn question audio into text with faster-whisper `small.en`, loaded once at startup · GitHub milestone: #2

| Task | FR | Files | Done when | Test | Issue | Done |
| --- | --- | --- | --- | --- | --- | --- |
| M2-T1 | FR-4 | requirements.txt, server/config.py, server/stt.py (+ tests/test_stt.py) | Turns a question WAV into text with faster-whisper `small.en`; `load()` builds the model once from config `STT_MODEL`, `STT_DEVICE` ("cuda") and `STT_COMPUTE_TYPE` ("float16"), so "cpu"/"int8" needs only a config change; `transcribe(wav)` passes the WAV bytes to the model and returns the segment texts joined into one string; tests use a fake model (no download, GPU or CUDA) | pytest | #8 | [x] |
| M2-T2 | FR-4 | server/main.py (+ tests/test_server.py) | The FastAPI lifespan calls `stt.load()` once at startup, never per request; `/health` still returns 200; tests fake `stt.load` | pytest | #9 | [ ] |

Manual checks: with the CUDA 12 toolkit and cuDNN 9 installed, transcribe one short spoken 16 kHz mono WAV with a one-off command against `stt`; the text matches what was said and the command prints how long one transcription takes (target ≤ 1 s, FR-4). The first run downloads the small.en model. "≥ 90% keep their meaning" is measured in M7.

## M3 (v1): Gemini answers with Search | planned
Goal: Spike Search + function calling with our key, then `llm.ask` with the system instruction, current time and the `searched` flag · FRs: FR-5, FR-6 · Tasks: not planned yet

## M4 (v1): TTS and full /query pipeline with server errors | planned
Goal: Piper TTS at 16 kHz; /query runs STT → LLM → TTS with 400/500 errors and one log line per query · FRs: FR-11, FR-16, FR-17 (one line per query) · Tasks: not planned yet

## M5 (v1): Tools: notes and reminders | planned
Goal: SQLite store, the five tools, the tool-call loop, repeat-back answers and the reminder endpoints · FRs: FR-7, FR-8, FR-9, FR-10, FR-12, FR-13, FR-14 · Tasks: not planned yet

## M6 (v1): PC client | planned
Goal: Push-to-talk recording, status sounds, 20 s timeout and due-reminder polling · FRs: FR-1, FR-2, FR-3, FR-15 (Due reminders target) · Tasks: not planned yet

## M7 (v1): Evaluation and reliability | planned
Goal: Frozen questions.csv and run_eval.py; meet the correctness, latency, transcription, reliability and secrets targets · FRs: quality targets; settles how eval questions are spoken · Tasks: not planned yet
