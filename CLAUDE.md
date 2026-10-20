# AI Assistant (voice now, glasses later)

Final goal: a learning companion worn as glasses: it sees what I study,
answers briefly, tracks what I learn and quizzes me, remembers me, and helps
run my day.
Current version: **v3 Memory** (tag v0.3.0); its milestones start at M13.
Versions v1–v7 are in `docs/roadmap.md`.

v3: push-to-talk PC client (Right Alt = voice, Right Ctrl = voice + screenshot;
no F9) → FastAPI server on 127.0.0.1: STT (faster-whisper, local) →
Gemini 3.5 Flash-Lite with function calling and the screenshot as an image
(web_search via Tavily; notes, reminders and concepts in SQLite) → TTS (Piper,
local) → answer WAV back. A 120 s in-memory session keeps the last 5 turns for
follow-ups; "quiz me" quizzes logged concepts. The client polls for due
reminders and speaks them. New in v3: a profile of fixed slots
(`config/profile.yaml`, schema in `config/profile_schema.yaml`) is in every
prompt; memory items (key points of about 12 words, in SQLite) are stored with
"remember that ...", recalled by question through SQLite FTS5 search, listed,
forgotten or wiped, and a session writer keeps 0 to 3 key points when a
session ends.

<!-- Doc paths are in backticks, not @-imports, so they load only when Claude opens them. -->
## Doc map (source of truth)
- `docs/roadmap.md`: final goal, versions v1–v7, process rule
- `docs/brief.md`: current version's scope, out of scope, success criteria
- `docs/spec.md`: current version's FRs, API contract, tool functions, quality targets, test plan
- `docs/design.md`: current version's architecture, stack, storage, repo layout, timeouts, decisions
- `docs/plan.md`: milestones and tasks (IDs like M1-T2), written by /plan-milestone
- `docs/hardware_plan.md`: parts, pin map, firmware board settings;
  read only for v7
- `docs/archive/vN/`: finished versions' docs; history only, never a source for current work
Docs win over code. If docs are unclear or contradict each other, stop and ask; don't guess.

## Process rule
- Only the current version has detailed docs (brief, spec, design, plan).
- At the end of a version: copy them to `docs/archive/vN/`, tag the release, then write the next
  version's docs. Milestone IDs continue across versions.

## Project structure (files go only here; ask before adding anything)
```text
ai-glasses/
├── CLAUDE.md  README.md  requirements.txt  .env.example  .gitignore  .gitattributes
├── docs/                  # roadmap, brief, spec, design, plan, hardware_plan, archive/
├── server/
│   ├── main.py            # FastAPI app: /query, /session/reset,
│   │                      # /reminders/*, /health; knows the stage order
│   ├── config.py          # all server settings; reads .env
│   ├── stt.py             # faster-whisper
│   ├── llm.py             # Gemini + tool-call loop + system instruction
│   ├── session.py         # in-memory session: 5 turns, image, quiz state
│   ├── tools.py           # tool declarations, dispatch, spoken reminder text
│   ├── search.py          # Tavily web search for the web_search tool
│   ├── store.py           # SQLite: notes, reminders and concepts
│   ├── tts.py             # Piper + resample to 16 kHz
│   └── logger.py          # JSONL line
├── client_pc/
│   ├── client.py          # two keys, screenshot, sounds, reminder polling
│   └── config.py          # server address, key, timeouts, poll interval
├── tests/
│   ├── conftest.py        # shared fixtures, fakes, temporary database
│   ├── test_server.py     # endpoint tests
│   ├── test_session.py    # session.py logic
│   └── test_<module>.py   # one module's own logic
├── eval/
│   ├── questions.json     # frozen 30-question eval set
│   ├── questions_v2.json  # v2 eval set, frozen after its first run
│   ├── config.py          # eval paths, pacing
│   ├── record.py          # records the 30 clips into data/eval/
│   ├── run_eval.py        # runs the eval: accuracy + latency
│   ├── run_eval_v2.py     # runs the v2 eval; reuses run_eval.py helpers
│   ├── live_questions.md  # 10 questions to speak with the key
│   ├── live_log.py        # prints the last 10 logged queries
│   └── results/           # <date>.md and .json per run
├── data/                  # assistant.db; eval/ clips; gitignored
│   └── eval_v2/           # v2 clips and screenshots/ for Look questions
├── models/                # Piper voice files, gitignored
├── logs/                  # queries.jsonl, gitignored
└── .claude/               # Claude Code setup: skills, agents, settings
    └── hooks/
        ├── guard-shell.sh       # blocks secrets and unsafe git (PreToolUse); .ps1 on Windows
        ├── format-python.sh     # ruff format + check after edits (PostToolUse); .ps1 on Windows
        └── test-guard-shell.sh  # cases for guard-shell.sh; .ps1 on Windows
```

## Spec-first rules
- Every task, test, commit and PR names the FR ID it serves (e.g. FR-4). No FR, no code.
- Never build anything in brief.md "Out of scope" or from a later version in roadmap.md.
- The API contract in spec.md is frozen: later clients depend on it. Ask first.
- Don't edit roadmap.md, brief.md, spec.md, design.md or hardware_plan.md unless asked; propose changes in chat.

## Fixed values (ask before changing)
- Audio: 16 kHz, mono, 16-bit WAV everywhere, in and out
- Gemini: `gemini-3.5-flash-lite` via `google-genai`, minimal thinking, 10 s timeout per call (API minimum),
  the tool functions (incl. `web_search`, run by the server against Tavily)
  in every request, at most 3 tool rounds,
  answers at most 3 sentences and 60 words; lists up to 5 items.
  Home city for weather comes from config.
- LLM stage deadline 15 s: a Gemini call starts only if its full timeout fits in the time left;
  the first search always runs; a later tool round needs elapsed + tool timeout + 10 s <= 18 s;
  one last call without tools may start by 8 s. Search timeout 5 s. Worst case STT + LLM + TTS
  = 20 s stays under the client's 25 s query timeout (reminder poll timeout stays 20 s).
- Time zone Asia/Kolkata; current date and time in the system instruction
- Server binds to 127.0.0.1 in v2
- Client query timeout 25 s; recording max 10 s; reminder poll every 10 s; "missed" after 60 s
- /query: 400 `{"error": "<reason>"}` if audio is missing or unreadable;
  400 `{"error": "image is not a readable image"}` (not JPEG or PNG) and
  400 `{"error": "image too large"}` (over 2 MB), checked before any stage;
  500 `{"error": "<stage>: <reason>"}` if a stage fails; the server never crashes
- Every query, failed ones included, writes one JSONL line: question, answer, per-stage timings,
  searched or not, tool calls (each ok, failed or refused), error,
  image sent or not (never the image), session continued or not, concept logged

## Code rules
- Files go only where "Project structure" shows. No new files or folders without asking.
- One job per file. One module per stage in `server/` (stt, llm, tts, logger): one stage function
  each, plus `load()` for stt and tts; `tools`, `search` and `store` serve the llm stage and the reminder
  endpoints. Only `server/main.py` knows the stage order.
- No hard-coded tunable values (ports, hosts, model names, timeouts, paths, sample rates, limits,
  intervals, time zone, home city). They live in `server/config.py` and `client_pc/config.py`.
- Write the least code that meets the task's acceptance criteria. No extra features, options or
  "future-proofing"; no unused code, commented-out code or debug prints.
- Short functions, clear names, type hints on public functions. Comment only the non-obvious why.
- Don't guess. If an API, CLI flag, file or requirement isn't in the docs or code, look it up
  in the current library docs or ask. Never invent names.
- No new dependency without asking; every dependency goes in `requirements.txt`.
- Pillow is pending approval until the Look spike; don't add it before then.
- Models load once at startup, never per request. Python 3.11, ruff for lint + format.
- FastAPI/pytest details: `server-conventions` skill. Git details: `git-workflow` skill.

## Commands (bash on Ubuntu; always call the venv's python, never a global one)
```bash
python3.11 -m venv .venv                                  # create the venv once
.venv/bin/python -m pip install -r requirements.txt       # after any dependency change
.venv/bin/python -m server.main                           # run server (host and port from server/config.py)
.venv/bin/python -m client_pc.client                      # run PC client (start the server first)
.venv/bin/python -m pytest -q                              # all tests; must pass before any commit
.venv/bin/python -m ruff check .                           # lint
.venv/bin/python -m ruff format --check .                  # format check
.venv/bin/python -m eval.record                            # record the 30 eval clips once
.venv/bin/python -m eval.run_eval                          # 30-question eval; real Gemini, slow
.venv/bin/python -m eval.record --set v2                   # record v2 clips
.venv/bin/python -m eval.run_eval_v2                       # v2 eval; slow
.venv/bin/python -m eval.live_log                          # last 10 logged queries
```
Use bash syntax: forward-slash paths. `&&` works, but one command per line is still preferred for git.
Client microphone: it stays open while the client runs, frames are discarded unless the key is held,
and nothing is stored.

## Testing
- Tests come from the task's acceptance criteria, written before the code. Name: `test_fr<N>_<what>`.
- `pytest` needs no network and no GPU: Gemini, whisper and Piper are faked; SQLite uses a temporary file.
  Real models, live search answers and latency are checked only by `run_eval.py`.

## Git
- One branch per milestone: `feature/m<N>-<slug>`. Every change, plan.md included, goes there. Never commit to `main`.
- One commit per task, message names the FR: `feat(server): add /health (FR-18)`.
- Merge only through /ship-milestone, after pytest + ruff pass. Each task passes review before its commit.
- After the last milestone of a version, /ship-milestone tags it
  (v0.2.0 for v2).

## Never
- Commit `.env`, OAuth tokens, certificates or databases (`data/`, `*.db`)
- Print or log API keys or tokens (the Gemini and Tavily keys, later `AUTH_TOKEN` and OAuth tokens)
- Send anything but the search query to Tavily: no notes, reminders, concepts,
  screenshots or screen content, or (from v3) memory content
  in a `web_search` query (Tavily may use queries to improve its models)
- Commit `logs/`, `.venv/`, `models/`, or model files
- Edit `eval/questions.json` after the first eval run: the set is frozen (only an obvious error, logged in plan.md)
- Edit `eval/questions_v2.json` after its first run: frozen the same way
- Add a dependency without adding it to `requirements.txt`
- `git push --force` or rewrite pushed history
