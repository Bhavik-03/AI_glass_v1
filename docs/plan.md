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

## M9 (v2): Look | done
Goal: Right Alt voice, Right Ctrl voice + screenshot; image to Gemini and in the session · GitHub milestone: #9

| Task | FR | Files | Done when | Test | Issue | Done |
| --- | --- | --- | --- | --- | --- | --- |
| M9-T1 | FR-19, FR-1 | docs/plan.md (spike scripts not committed) | Spike results recorded here: ImageGrab capture time; what it captures with two monitors (main screen only by default); size and look of a 1280 px JPEG at a few qualities and the chosen `SCREENSHOT_JPEG_QUALITY`; whether pynput reports Right Alt as `alt_r` or `alt_gr`, and Right Ctrl as `ctrl_r`. Pillow is installed in `.venv` for the spike only | manual | #74 | [x] |
| M9-T2 | FR-1 | client_pc/config.py, client_pc/client.py (+ tests/test_client.py) | `VOICE_KEY = "alt_gr"` (from M9-T1) replaces `PTT_KEY = "f9"`; Right Alt starts and stops recording as F9 did; the extra `ctrl_l` press Right Alt sends starts nothing; F9 no longer does | pytest | #75 | [x] |
| M9-T3 | FR-20, FR-16 | requirements.txt, server/config.py, server/main.py (+ tests/test_server.py) | `/query` takes an optional `image`; over `IMAGE_MAX_BYTES` gives 400 `{"error": "image too large"}`; not JPEG or PNG gives 400 `{"error": "image is not a readable image"}`; both before any stage; without an image, `/query` works as before. Pillow goes into requirements.txt after approval | pytest | #76 | [x] |
| M9-T4 | FR-20 | server/llm.py, .claude/skills/server-conventions/SKILL.md (+ tests/test_llm.py) | `ask(question, now, turns=(), image=None)`, image as bytes plus MIME type; with an image the Gemini request has an image part next to the question (fake client); without one the request is unchanged | pytest | #77 | [x] |
| M9-T5 | FR-21 | server/session.py (+ tests/test_session.py) | The session keeps the most recent image (bytes and type); it ends with the session at 120 s; `reset()` clears it | pytest | #78 | [x] |
| M9-T6 | FR-20, FR-21, FR-17 | server/main.py (+ tests/test_server.py) | `/query` sends the new image to `llm.ask`, else the saved one; the image is saved only after a 200; the log has `image_sent` (true only for a new image), never the image | pytest | #79 | [x] |
| M9-T7 | FR-3 | client_pc/client.py (+ tests/test_client.py) | `send_query(wav, image=None)` adds an `image` field (JPEG) only when given; the 25 s timeout and error sound behave as before | pytest | #80 | [x] |
| M9-T8 | FR-19 | client_pc/config.py, client_pc/client.py (+ tests/test_client.py) | Right Ctrl (`LOOK_KEY = "ctrl_r"`) records like Right Alt and takes one screenshot at press, not release; shrunk to `SCREENSHOT_MAX_SIDE_PX` (1280), JPEG in memory; Right Alt sends no image; releasing the other key does not stop the recording; no image file is written (fake screen grab) | pytest | #81 | [x] |

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

## M10 (v2): Concept tracker | done
Goal: concepts table, `log_concept` and `learned_this_week`, names in the prompt · GitHub milestone: #10

| Task | FR | Files | Done when | Test | Issue | Done |
| --- | --- | --- | --- | --- | --- | --- |
| M10-T1 | FR-5 | server/llm.py (+ tests/test_llm.py) | The system instruction says the user is an engineering student learning AI/ML, so ambiguous terms take the AI/ML meaning (M8 manual check: 'Lora' was answered as LoRa radio); a test checks `system_instruction()` contains it | pytest | #83 | [x] |
| M10-T2 | FR-23 | server/store.py (+ tests/test_store.py) | A `concepts` table (id, name unique case-insensitive, summary, first_asked, last_asked, status new/right/wrong, last_quizzed empty); `log_concept(name, summary, now)` adds a row with status new and first and last asked set, or for a name matching case-insensitively updates `last_asked` and the summary and adds no row; returns `{name, summary, status, new}`; `concept_names()` lists the names; temp DB | pytest | #84 | [x] |
| M10-T3 | FR-23 | server/tools.py (+ tests/test_tools.py) | Declaration `log_concept(name, summary)`; dispatch returns `{name, summary, status, new}`; a missing or empty name or summary returns `{error}` and stores nothing | pytest | #85 | [x] |
| M10-T4 | FR-25 | server/config.py, server/store.py, server/tools.py (+ tests/test_store.py, tests/test_tools.py) | Declaration `learned_this_week()` returns `{count, names}`; with 7 concepts first asked in the last `LEARNED_DAYS` (7) days and 2 older, count 7 and the `LEARNED_MAX_NAMES` (5) most recent names; with none, count 0 and no names | pytest | #86 | [x] |
| M10-T5 | FR-23, FR-5 | server/llm.py (+ tests/test_llm.py) | The system instruction says to call `log_concept` for learning questions only ("what is LoRA?" is one, "when is Diwali?" is not), to reuse a listed name for the same concept, and never to put concepts in a `web_search` query; it lists the existing concept names from `store` (temp DB, fake client) | pytest | #87 | [x] |
| M10-T6 | FR-17 | server/main.py (+ tests/test_server.py) | Every `/query` log line has `concept`: the name from an ok `log_concept` call in that query, else null; failed queries included | pytest | #88 | [x] |
| M10-T7 | FR-5 | server/tools.py (+ tests/test_tools.py) | The `web_search` declaration says the query must never contain note, reminder, concept or screen content; a test checks the text | pytest | #89 | [x] |

Manual checks: with the real model, "what is LoRA?" adds one concept row with status new and
the answer is about the fine-tuning method; asking "what is lora used for?" later updates that
row and adds none; "when is Diwali?" adds none; "what did I learn this week?" gives the count
and names within the FR-5 limit (FR-23, FR-25). The 20-question concept target is checked in
the M12 eval.

## M11 (v2): Quiz me | in progress
Goal: `start_quiz`, quiz state in the session, stop, grading call, score, 300 s wait · GitHub milestone: #11

| Task | FR | Files | Done when | Test | Issue | Done |
| --- | --- | --- | --- | --- | --- | --- |
| M11-T1 | FR-24 | server/config.py, server/store.py (+ tests/test_store.py) | `quiz_concepts(limit)` gives status new first (oldest first asked first), then status wrong (oldest last quizzed first), never right; with 4 new and 1 wrong and `QUIZ_MAX_CONCEPTS` (3), the 3 oldest new; with only wrong ones, the oldest last quizzed first; `set_quiz_result(name, correct, now)` sets status right or wrong and `last_quizzed`, deletes nothing; a concept set right is not picked again, one set wrong is; temp DB | pytest | #91 | [ ] |
| M11-T2 | FR-24, FR-22 | server/config.py, server/session.py (+ tests/test_session.py) | The session holds a quiz (concepts, current index, right count) behind the lock; `start_quiz`, `quiz(now)`, advancing after a graded answer and `end_quiz()`; the 120 s session expiry does not end a running quiz; with no answer for `QUIZ_ANSWER_WAIT_S` (300) after the last question the quiz ends quietly and no concept status changes; `reset()` also clears a running quiz | pytest | #92 | [ ] |
| M11-T3 | FR-24 | server/config.py, server/tools.py (+ tests/test_tools.py) | Declaration `start_quiz()`; dispatch picks up to `QUIZ_MAX_CONCEPTS` from `store`, starts the session quiz and returns `{count, question}` with `question` from `QUIZ_QUESTION` ("Explain {name} in one sentence."); with no concept to quiz, `{count: 0, question: ""}` and no quiz starts; the score text is "2 of 3 right" | pytest | #93 | [ ] |
| M11-T4 | FR-24 | server/llm.py (+ tests/test_llm.py) | The system instruction says to call `start_quiz` only when the user asks ("quiz me"), to read the returned question exactly, and to say there is nothing to quiz when `count` is 0; a test checks `system_instruction()` contains it | pytest | #94 | [ ] |
| M11-T5 | FR-24 | server/llm.py (+ tests/test_llm.py) | `grade(name, summary, answer)` makes one Gemini call with no tools, `LLM_TIMEOUT_S`, JSON output `{correct, feedback}` (one line: right or wrong plus a short correction); the prompt holds the concept name, its summary and the answer, and tells Gemini to judge the meaning and ignore speech recognition errors in the spoken answer; an error or unreadable JSON raises, so the stage fails (fake client checks the request) | pytest | #95 | [ ] |
| M11-T6 | FR-24, FR-17 | server/main.py, tests/conftest.py (+ tests/test_server.py) | While a quiz runs, every `/query` after STT is graded as the answer by `llm.grade` and `llm.ask` is not called, even for a transcript that sounds like a question ("what is LoRA?"); `store` saves the grade; the spoken answer is the feedback plus the next question, or plus the score after the last one, which ends the quiz; a grading failure is 500 `{"error": "llm: <reason>"}` and the quiz stays on the same question; every quiz query writes its log line | pytest | #96 | [ ] |
| M11-T7 | FR-24, FR-22 | server/config.py, server/main.py (+ tests/test_server.py) | A transcript containing `QUIZ_STOP_PHRASE` ("stop quiz", lowercase, no punctuation) ends the quiz with the answer "Quiz stopped.", no Gemini call, statuses so far kept; an answer after 300 s goes to `llm.ask` as a normal question and the concept's status is unchanged; a quiz answer at 200 s after the 120 s session TTL is still graded; after `POST /session/reset` the next `/query` goes to `llm.ask` with no quiz running | pytest | #97 | [ ] |

Manual checks: with the real model and a few logged concepts, "quiz me" asks "Explain <name>
in one sentence.", each spoken answer gets one line of right or wrong plus a correction, and
the end speaks the score; with no concepts it says there is nothing to quiz; ordinary
questions never start a quiz (FR-24). Grading agreement (≥ 8 of 10) is checked in the M12 eval.

## M12 (v2): Evaluation | planned
Goal: frozen v2 set, `record --set v2`, `run_eval_v2`, v1 regression, README, tag v0.2.0
FRs: all v2 quality targets · Tasks: not planned yet

Notes: FR-2, FR-4, FR-6 to FR-15 and FR-18 are unchanged from v1; the v1 regression run
in M12 checks them. Issue #38 stays open for v6.
