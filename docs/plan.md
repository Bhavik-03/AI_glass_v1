# Plan: AI Assistant v2 Teacher

## M8 (v2): Sessions and follow-ups | done
Goal: follow-ups and "tell me more" for 120 s, new answer limits, tool status in the log · GitHub milestone: #8

| Task | FR | Files | Done when | Test | Issue | Done |
| --- | --- | --- | --- | --- | --- | --- |
| M8-T1 | FR-17 | server/llm.py, .claude/skills/server-conventions/SKILL.md (+ tests/test_llm.py) | Each tool call is `{name, args, status}`: "refused" when skipped for lack of time, "failed" on an error result, else "ok" (#59) | pytest | #65 | [x] |
| M8-T2 | FR-17 | eval/run_eval.py (+ tests/test_run_eval.py) | A tool call counts as made only when its `status` is "ok" (#59); `eval/live_log.py` does not read `ok`, so it needs no change | pytest | #66 | [x] |
| M8-T3 | FR-5 | server/config.py, server/llm.py (+ tests/test_llm.py) | The system instruction says at most 3 sentences and 60 words; a list says the total count and the first 5 (newest notes, soonest reminders); "tell me more" gives the next 5 within the same limit; values from `ANSWER_MAX_SENTENCES`, `ANSWER_MAX_WORDS`, `LIST_MAX_ITEMS` | pytest | #67 | [x] |
| M8-T4 | FR-21 | server/config.py, server/session.py (+ tests/test_session.py) | `add_turn`, `turns(now)` and `reset()` behind a lock; keeps the last 5 question and answer texts; no turns 120 s after the last answer; values from `SESSION_TTL_S`, `SESSION_MAX_TURNS` | pytest | #68 | [x] |
| M8-T5 | FR-21 | server/llm.py, .claude/skills/server-conventions/SKILL.md (+ tests/test_llm.py) | `ask(question, now, turns)` sends the earlier turns as user and model text before the question; a fake-client test checks the request contents | pytest | #69 | [x] |
| M8-T6 | FR-21, FR-17 | server/main.py, tests/conftest.py (+ tests/test_server.py) | `/query` passes the session turns to `llm.ask` and adds a turn only after a 200; a failed query adds no turn and does not extend the 120 s; the log line has `session_continued` | pytest | #70 | [x] |
| M8-T7 | FR-22 | server/main.py (+ tests/test_server.py) | `POST /session/reset` returns 200 `{"status": "ok"}` and clears the session; 200 also with no session | pytest | #71 | [x] |
| M8-T8 | FR-22 | eval/run_eval.py (+ tests/test_run_eval.py) | The v1 eval calls `POST /session/reset` before each clip, so rows do not share context | pytest | #72 | [x] |

Manual checks: with the real model, ask "what is LoRA?", then "what is it used for?" and hear an
answer about LoRA (FR-21); the same follow-up after 120 s is answered as a new question; with 7
notes, the list says the count and 5 notes, and "tell me more" gives the rest (FR-5).

## M9 (v2): Look | in progress
Goal: Right Alt voice, Right Ctrl voice + screenshot; image to Gemini and in the session · GitHub milestone: #9

| Task | FR | Files | Done when | Test | Issue | Done |
| --- | --- | --- | --- | --- | --- | --- |
| M9-T1 | FR-19, FR-1 | docs/plan.md (spike scripts not committed) | Spike results recorded here: ImageGrab capture time; what it captures with two monitors (main screen only by default); size and look of a 1280 px JPEG at a few qualities and the chosen `SCREENSHOT_JPEG_QUALITY`; whether pynput reports Right Alt as `alt_r` or `alt_gr`, and Right Ctrl as `ctrl_r`. Pillow is installed in `.venv` for the spike only | manual | #74 | [x] |
| M9-T2 | FR-1 | client_pc/config.py, client_pc/client.py (+ tests/test_client.py) | `VOICE_KEY = "alt_gr"` (from M9-T1) replaces `PTT_KEY = "f9"`; Right Alt starts and stops recording as F9 did; the extra `ctrl_l` press Right Alt sends starts nothing; F9 no longer does | pytest | #75 | [ ] |
| M9-T3 | FR-20, FR-16 | requirements.txt, server/config.py, server/main.py (+ tests/test_server.py) | `/query` takes an optional `image`; over `IMAGE_MAX_BYTES` gives 400 `{"error": "image too large"}`; not JPEG or PNG gives 400 `{"error": "image is not a readable image"}`; both before any stage; without an image, `/query` works as before. Pillow goes into requirements.txt after approval | pytest | #76 | [ ] |
| M9-T4 | FR-20 | server/llm.py, .claude/skills/server-conventions/SKILL.md (+ tests/test_llm.py) | `ask(question, now, turns=(), image=None)`, image as bytes plus MIME type; with an image the Gemini request has an image part next to the question (fake client); without one the request is unchanged | pytest | #77 | [ ] |
| M9-T5 | FR-21 | server/session.py (+ tests/test_session.py) | The session keeps the most recent image (bytes and type); it ends with the session at 120 s; `reset()` clears it | pytest | #78 | [ ] |
| M9-T6 | FR-20, FR-21, FR-17 | server/main.py (+ tests/test_server.py) | `/query` sends the new image to `llm.ask`, else the saved one; the image is saved only after a 200; the log has `image_sent` (true only for a new image), never the image | pytest | #79 | [ ] |
| M9-T7 | FR-3 | client_pc/client.py (+ tests/test_client.py) | `send_query(wav, image=None)` adds an `image` field (JPEG) only when given; the 25 s timeout and error sound behave as before | pytest | #80 | [ ] |
| M9-T8 | FR-19 | client_pc/config.py, client_pc/client.py (+ tests/test_client.py) | Right Ctrl (`LOOK_KEY = "ctrl_r"`) records like Right Alt and takes one screenshot at press, not release; shrunk to `SCREENSHOT_MAX_SIDE_PX` (1280), JPEG in memory; Right Alt sends no image; releasing the other key does not stop the recording; no image file is written (fake screen grab) | pytest | #81 | [ ] |

M9-T1 spike results (Oct 14, 2026; Pillow 12.3.0, pynput 1.8.2):
- `ImageGrab.grab()` of the 1920x1080 screen: median 29 ms, max 49 ms (10 grabs).
- Two monitors: only one was connected; `all_screens=True` gave the same 1920x1080. By
  default `grab()` takes the primary screen only. Not measured with a second monitor.
- `thumbnail((1280, 1280))` to 1280x720: 39 ms. JPEG of a code editor screen: quality 50 =
  59 KB, 60 = 66 KB, 70 = 76 KB, 80 = 92 KB, 90 = 128 KB; encode about 5 ms. Small text is
  readable at 60 and 80; 60 is slightly softer. Chosen: `SCREENSHOT_JPEG_QUALITY = 70`.
- Keys (checked by hand): Right Alt sends `Key.ctrl_l` then `Key.alt_gr`; Right Ctrl sends
  `Key.ctrl_r`. So `VOICE_KEY = "alt_gr"` (M9-T2) and `LOOK_KEY = "ctrl_r"` (M9-T8); the
  extra `ctrl_l` press must not start anything.

Manual checks: Right Alt speech clear on playback in 20 of 20 tests (FR-1); Right Ctrl on a
graph, ask "what is this graph?" and hear an answer about it (FR-19); a follow-up within 120 s
uses the same screenshot (FR-21). The 8 s median with an image is checked in the M12 eval.

## M10 (v2): Concept tracker | planned
Goal: concepts table, `log_concept` and `learned_this_week`, names in the prompt
FRs: FR-23, FR-25, FR-17 · Tasks: not planned yet
Add to the system instruction that the user is an engineering student learning AI/ML, so
ambiguous terms take the AI/ML meaning (found in the M8 manual check: 'Lora' was answered as
LoRa radio).

## M11 (v2): Quiz me | planned
Goal: `start_quiz`, quiz state in the session, stop, grading call, score, 300 s wait
FRs: FR-24, FR-22 · Tasks: not planned yet

## M12 (v2): Evaluation | planned
Goal: frozen v2 set, `record --set v2`, `run_eval_v2`, v1 regression, README, tag v0.2.0
FRs: all v2 quality targets · Tasks: not planned yet

Notes: FR-2, FR-4, FR-6 to FR-15 and FR-18 are unchanged from v1; the v1 regression run
in M12 checks them. Issue #38 stays open for v6.
