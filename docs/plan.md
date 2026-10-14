# Plan: AI Assistant v2 Teacher

## M8 (v2): Sessions and follow-ups | in progress
Goal: follow-ups and "tell me more" for 120 s, new answer limits, tool status in the log · GitHub milestone: #8

| Task | FR | Files | Done when | Test | Issue | Done |
| --- | --- | --- | --- | --- | --- | --- |
| M8-T1 | FR-17 | server/llm.py, .claude/skills/server-conventions/SKILL.md (+ tests/test_llm.py) | Each tool call is `{name, args, status}`: "refused" when skipped for lack of time, "failed" on an error result, else "ok" (#59) | pytest | #65 | [x] |
| M8-T2 | FR-17 | eval/run_eval.py (+ tests/test_run_eval.py) | A tool call counts as made only when its `status` is "ok" (#59); `eval/live_log.py` does not read `ok`, so it needs no change | pytest | #66 | [x] |
| M8-T3 | FR-5 | server/config.py, server/llm.py (+ tests/test_llm.py) | The system instruction says at most 3 sentences and 60 words; a list says the total count and the first 5 (newest notes, soonest reminders); "tell me more" gives the next 5 within the same limit; values from `ANSWER_MAX_SENTENCES`, `ANSWER_MAX_WORDS`, `LIST_MAX_ITEMS` | pytest | #67 | [x] |
| M8-T4 | FR-21 | server/config.py, server/session.py (+ tests/test_session.py) | `add_turn`, `turns(now)` and `reset()` behind a lock; keeps the last 5 question and answer texts; no turns 120 s after the last answer; values from `SESSION_TTL_S`, `SESSION_MAX_TURNS` | pytest | #68 | [x] |
| M8-T5 | FR-21 | server/llm.py, .claude/skills/server-conventions/SKILL.md (+ tests/test_llm.py) | `ask(question, now, turns)` sends the earlier turns as user and model text before the question; a fake-client test checks the request contents | pytest | #69 | [ ] |
| M8-T6 | FR-21, FR-17 | server/main.py, tests/conftest.py (+ tests/test_server.py) | `/query` passes the session turns to `llm.ask` and adds a turn only after a 200; a failed query adds no turn and does not extend the 120 s; the log line has `session_continued` | pytest | #70 | [ ] |
| M8-T7 | FR-22 | server/main.py (+ tests/test_server.py) | `POST /session/reset` returns 200 `{"status": "ok"}` and clears the session; 200 also with no session | pytest | #71 | [ ] |
| M8-T8 | FR-22 | eval/run_eval.py (+ tests/test_run_eval.py) | The v1 eval calls `POST /session/reset` before each clip, so rows do not share context | pytest | #72 | [ ] |

Manual checks: with the real model, ask "what is LoRA?", then "what is it used for?" and hear an
answer about LoRA (FR-21); the same follow-up after 120 s is answered as a new question; with 7
notes, the list says the count and 5 notes, and "tell me more" gives the rest (FR-5).

## M9 (v2): Look | planned
Goal: Right Alt voice, Right Ctrl voice + screenshot; image to Gemini and in the session
FRs: FR-19, FR-20, FR-1, FR-3, FR-16, FR-17 · Tasks: not planned yet

## M10 (v2): Concept tracker | planned
Goal: concepts table, `log_concept` and `learned_this_week`, names in the prompt
FRs: FR-23, FR-25, FR-17 · Tasks: not planned yet

## M11 (v2): Quiz me | planned
Goal: `start_quiz`, quiz state in the session, stop, grading call, score, 300 s wait
FRs: FR-24, FR-22 · Tasks: not planned yet

## M12 (v2): Evaluation | planned
Goal: frozen v2 set, `record --set v2`, `run_eval_v2`, v1 regression, README, tag v0.2.0
FRs: all v2 quality targets · Tasks: not planned yet

Notes: FR-2, FR-4, FR-6 to FR-15 and FR-18 are unchanged from v1; the v1 regression run
in M12 checks them. Issue #38 stays open for v6.
