# AI Assistant (voice now, glasses later)

Final goal: glasses that act as my second brain and handle quick phone tasks hands-free; memory stays on my machine.
Current version: **v1 Voice assistant** (tag v0.1.0). Versions v1–v5 are in `docs/roadmap.md`.

v1: push-to-talk PC client (one key) → FastAPI server on 127.0.0.1: STT (faster-whisper, local) →
Gemini 3 Flash with Google Search + function calling (notes and reminders in SQLite) → TTS (Piper,
local) → answer WAV back. The client polls for due reminders and speaks them.

<!-- Doc paths are in backticks, not @-imports, so they load only when Claude opens them. -->
## Doc map (source of truth)
- `docs/roadmap.md`: final goal, versions v1–v5, process rule
- `docs/brief.md`: current version's scope, out of scope, success criteria
- `docs/spec.md`: current version's FRs, API contract, tool functions, quality targets, test plan
- `docs/design.md`: current version's architecture, stack, storage, repo layout, timeouts, decisions
- `docs/plan.md`: milestones and tasks (IDs like M1-T2), written by /plan-milestone
- `docs/hardware_plan.md`: parts, pin map, firmware board settings; read only for v4 and v5
- `docs/archive/vN/`: finished versions' docs; history only, never a source for current work
Docs win over code. If docs are unclear or contradict each other, stop and ask; don't guess.

## Process rule
- Only the current version has detailed docs (brief, spec, design, plan).
- At the end of a version: copy them to `docs/archive/vN/`, tag the release, then write the next
  version's docs. Milestone IDs continue across versions.

## Project structure (files go only here; ask before adding anything)
```text
ai-glasses/
├── CLAUDE.md  README.md  requirements.txt  .env.example  .gitignore
├── docs/                  # roadmap, brief, spec, design, plan, hardware_plan, archive/
├── server/
│   ├── main.py            # FastAPI app: /query, /reminders/*, /health; only file that knows stage order
│   ├── config.py          # all server settings; reads .env
│   ├── stt.py             # faster-whisper
│   ├── llm.py             # Gemini + Search + tool-call loop + system instruction
│   ├── tools.py           # tool declarations, dispatch, spoken reminder text
│   ├── store.py           # SQLite: notes and reminders
│   ├── tts.py             # Piper + resample to 16 kHz
│   └── logger.py          # JSONL line
├── client_pc/
│   ├── client.py          # push-to-talk key, sounds, reminder polling
│   └── config.py          # server address, key, timeouts, poll interval
├── tests/
│   ├── conftest.py        # shared fixtures, fakes, temporary database
│   ├── test_server.py     # endpoint tests
│   ├── test_<module>.py   # one module's own logic
│   ├── questions.csv      # frozen 30-question eval set
│   └── run_eval.py        # runs the eval: accuracy + latency
├── data/                  # assistant.db, gitignored
├── models/                # Piper voice files, gitignored
├── logs/                  # queries.jsonl, gitignored
└── .claude/               # Claude Code setup: skills, agents, settings
```

## Spec-first rules
- Every task, test, commit and PR names the FR ID it serves (e.g. FR-4). No FR, no code.
- Never build anything in brief.md "Out of scope" or from a later version in roadmap.md.
- The API contract in spec.md is frozen: later clients depend on it. Ask first.
- Don't edit roadmap.md, brief.md, spec.md, design.md or hardware_plan.md unless asked; propose changes in chat.

## Fixed values (ask before changing)
- Audio: 16 kHz, mono, 16-bit WAV everywhere, in and out
- Gemini: a Gemini 3 Flash model via `google-genai`, minimal thinking, 8 s timeout per call,
  Google Search and the tool functions in every request, at most 3 tool rounds, answers ≤ 2 short
  sentences (< 40 words) except lists. Home city for weather comes from config.
- Time zone Asia/Kolkata; current date and time in the system instruction
- Server binds to 127.0.0.1 in v1
- Client timeout 20 s; recording max 10 s; reminder poll every 10 s; "missed" after 60 s
- /query: 400 `{"error": "<reason>"}` if audio is missing or unreadable;
  500 `{"error": "<stage>: <reason>"}` if a stage fails; the server never crashes
- Every query, failed ones included, writes one JSONL line: question, answer, per-stage timings,
  searched or not, tool calls, error

## Code rules
- Files go only where "Project structure" shows. No new files or folders without asking.
- One job per file. One module per stage in `server/` (stt, llm, tts, logger): one stage function
  each, plus `load()` for stt and tts; `tools` and `store` serve the llm stage and the reminder
  endpoints. Only `server/main.py` knows the stage order.
- No hard-coded tunable values (ports, hosts, model names, timeouts, paths, sample rates, limits,
  intervals, time zone, home city). They live in `server/config.py` and `client_pc/config.py`.
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
.venv\Scripts\python -m server.main                       # run server (host and port from server/config.py)
.venv\Scripts\python -m pytest -q                          # all tests; must pass before any commit
.venv\Scripts\python -m ruff check .                       # lint
.venv\Scripts\python -m ruff format --check .              # format check
.venv\Scripts\python tests\run_eval.py                     # 30-question eval; real Gemini, slow
```
Use PowerShell syntax: run commands on separate lines, not `&&` (Windows PowerShell 5.1 lacks it).

## Testing
- Tests come from the task's acceptance criteria, written before the code. Name: `test_fr<N>_<what>`.
- `pytest` needs no network and no GPU: Gemini, whisper and Piper are faked; SQLite uses a temporary file.
  Real models, live search answers and latency are checked only by `run_eval.py`.

## Git
- One branch per milestone: `feature/m<N>-<slug>`. Every change, plan.md included, goes there. Never commit to `main`.
- One commit per task, message names the FR: `feat(server): add /health (FR-18)`.
- Merge only through /ship-milestone, after pytest + ruff pass. Each task passes review before its commit.
- After the last milestone of a version, /ship-milestone tags it (v0.1.0 for v1).

## Never
- Commit `.env`, OAuth tokens, certificates or databases (`data/`, `*.db`)
- Print or log API keys or tokens (the Gemini key, later `AUTH_TOKEN` and OAuth tokens)
- Commit `logs/`, `.venv/`, `models/`, or model files
- Edit `tests/questions.csv` after the first eval run: the set is frozen
- Add a dependency without adding it to `requirements.txt`
- `git push --force` or rewrite pushed history
