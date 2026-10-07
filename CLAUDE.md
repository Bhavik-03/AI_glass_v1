# AI Assistant Glasses v1

Push-to-talk assistant with two buttons. Look sends a question (WAV) + photo (JPEG); Ask sends only
the question. One FastAPI server on the laptop: STT (faster-whisper, local) → Gemini with Google
Search → TTS (Piper, local) → answer WAV back. Phase A client = laptop webcam app.
Phase B client = XIAO ESP32-S3 glasses. Both use the same API.

<!-- Doc paths are in backticks, not @-imports, so they load only when Claude opens them. -->
## Source of truth
- `docs/brief.md`: scope, out of scope, success criteria
- `docs/spec.md`: FR-1…FR-11, API contract, quality targets, test plan
- `docs/design.md`: architecture, stack, repo layout, timeouts, decisions
- `docs/expense_v1.md`: hardware, pin map, firmware board settings (Phase B)
- `docs/plan.md`: milestones and tasks (IDs like M1-T2), written by /plan-milestone
Docs win over code. If docs are unclear or contradict each other, stop and ask; don't guess.

## Project structure (files go only here; ask before adding anything)
```text
ai-glasses/
├── CLAUDE.md  README.md  requirements.txt  .env.example  .gitignore
├── docs/                  # brief, spec, design, expense_v1, plan (source of truth)
├── server/
│   ├── main.py            # FastAPI app: /query, /health; only file that knows stage order
│   ├── config.py          # all server settings; reads .env
│   ├── stt.py             # faster-whisper
│   ├── vlm.py             # Gemini + Google Search + system instruction
│   ├── tts.py             # Piper + resample to 16 kHz
│   └── logger.py          # JSONL line + photo
├── client_pc/
│   ├── client.py          # Phase A: webcam, mic, Look/Ask keys, tones
│   └── config.py          # server IP/port, keys, timeouts
├── firmware/glasses/
│   ├── glasses.ino        # Phase B: buttons, camera, mic, HTTP, tones
│   ├── config.example.h   # template, committed
│   └── config.h           # Wi-Fi + server IP, gitignored
├── tests/
│   ├── conftest.py        # shared fixtures and fakes
│   ├── test_server.py     # endpoint tests
│   ├── test_<module>.py   # one module's own logic
│   ├── questions.csv      # frozen 30-question eval set
│   └── run_eval.py        # runs the eval: accuracy + latency
├── models/                # Piper voice files, gitignored
├── logs/                  # queries.jsonl + photos, gitignored
└── .claude/               # Claude Code setup: skills, agents, settings
```

## Spec-first rules
- Every task, test, commit and PR names the FR ID it serves (e.g. FR-4). No FR, no code.
- Never build anything in brief.md "Out of scope" (streaming audio, wake word, local VLM, multi-turn…).
- The API contract in spec.md is frozen: changing /query or /health breaks firmware. Ask first.
- Don't edit brief.md, spec.md, design.md or expense_v1.md unless asked; propose changes in chat.

## Fixed values (ask before changing)
- Audio: 16 kHz, mono, 16-bit WAV everywhere, in and out
- Image: optional; when sent, 640×480 JPEG, never resized on the server
- Gemini: Flash or Flash-Lite via `google-genai`, minimal thinking, 8 s timeout, Google Search
  grounding on every request, answers ≤ 2 short sentences (< 40 words), photo used only when the
  question is about it. Home city for weather comes from config.
- Client timeout 20 s; recording max 10 s
- /query: 400 `{"error": "<reason>"}` if audio is missing or a file is unreadable;
  500 `{"error": "<stage>: <reason>"}` if a stage fails; the server never crashes
- Every query, failed ones included, writes one JSONL line: question, answer, per-stage timings,
  photo sent or not, Gemini searched or not, error

## Code rules
- Files go only where "Project structure" shows. No new files or folders without asking.
- One job per file. One module per stage in `server/` (stt, vlm, tts, logger): one stage
  function each, plus `load()` for stt and tts. Only `server/main.py` knows the stage order.
- No hard-coded tunable values (ports, IPs, model names, timeouts, paths, sample rates, limits, home city).
  They live in `server/config.py`, `client_pc/config.py`, `firmware/glasses/config.h`.
- Write the least code that meets the task's acceptance criteria. No extra features, options or
  "future-proofing"; no unused code, commented-out code or debug prints.
- Short functions, clear names, type hints on public functions. Comment only the non-obvious why.
- Don't guess. If an API, CLI flag, file or requirement isn't in the docs or code, look it up
  in the current library docs or ask. Never invent names.
- No new dependency without asking; every dependency goes in `requirements.txt`.
- Models load once at startup, never per request. Python 3.11, ruff for lint + format.
- FastAPI/pytest details: `server-conventions` skill. Git details: `git-workflow` skill.

## Commands (Windows PowerShell; always call the venv's python, never a global one)
```powershell
py -3.11 -m venv .venv                                    # create the venv once
.venv\Scripts\python -m pip install -r requirements.txt   # after any dependency change
.venv\Scripts\python -m uvicorn server.main:app --host 0.0.0.0 --port 8000   # run server
.venv\Scripts\python -m pytest -q                          # all tests; must pass before any commit
.venv\Scripts\python -m ruff check .                       # lint
.venv\Scripts\python -m ruff format --check .              # format check
.venv\Scripts\python tests\run_eval.py                     # 30-question eval; real Gemini, slow
```
Use PowerShell syntax: run commands on separate lines, not `&&` (Windows PowerShell 5.1 lacks it).
Firmware (Phase B): board settings are in `docs/expense_v1.md`. Before the first compile, find
the exact board ID with `arduino-cli board listall xiao`; don't guess it.

## Testing
- Tests come from the task's acceptance criteria, written before the code. Name: `test_fr<N>_<what>`.
- `pytest` needs no network and no GPU: Gemini, whisper and Piper are faked.
  Real models, live search answers and latency are checked only by `run_eval.py`.

## Git
- One branch per milestone: `feature/m<N>-<slug>`. Every change, plan.md included, goes there. Never commit to `main`.
- One commit per task, message names the FR: `feat(server): add /health (FR-9)`.
- Merge only through /ship-milestone, after pytest + ruff pass. Each task passes review before its commit.

## Never
- Commit, print or log secrets: `.env`, `firmware/glasses/config.h`, the Gemini key
- Commit `logs/`, `.venv/`, `models/`, or model files
- Edit `tests/questions.csv` after the first eval run: the set is frozen
- Add a dependency without adding it to `requirements.txt`
- `git push --force` or rewrite pushed history
