Version 1. See roadmap.md.

# AI Assistant v1 Spec: Voice assistant

Updated Oct 9, 2026 · Bhavik Fulfagar

v1 answers one spoken question or command with a spoken answer within 15 s, using one push-to-talk key on the laptop. It answers with live information (a `web_search` tool backed by a web search API), keeps notes and reminders in SQLite through Gemini function calling, and speaks reminders when they are due. Scope and out-of-scope items are in brief.md.

## How it works

A Python client and a FastAPI server run on the same laptop. The server binds to 127.0.0.1.

User flow, push-to-talk:

1. The user holds the key. The client plays the start sound and records.
2. The user releases the key. The client plays the thinking sound and sends the audio to `POST /query`.
3. The server transcribes the question and sends it to Gemini with the tool functions. Gemini may call `web_search`, the notes and reminder tools, or both; the server runs each call (web search API or SQLite) and returns the results to Gemini until it gives a final answer.
4. The server turns the answer into speech and returns the WAV.
5. The client plays the answer, or the error sound on failure.

Reminder flow: every 10 s the client asks `GET /reminders/due`. For each due reminder it prints the text, fetches and plays its audio, then acknowledges it. A reminder stays due until acknowledged, so none is lost if the client is closed.

## Functional requirements

Each ID later becomes one or more build tasks and tests. Fixed values (rates, timeouts, intervals, limits, model name, time zone) live in config files.

| ID | Requirement | Input → Output | Acceptance criteria |
| --- | --- | --- | --- |
| FR-1 | Record the question while the push-to-talk key is held, 10 s max | Key hold → WAV, 16 kHz mono 16-bit | Speech clear on playback in 20 of 20 tests; recording stops at release or at 10 s |
| FR-2 | Play status sounds: start sound on key press, thinking sound after release, error sound on any failure | Client events → sounds | The user can tell the state without a screen; the error sound plays on a 400, a 500, a timeout and a refused connection |
| FR-3 | Send the question to the server with a 20 s client timeout | WAV → `POST /query` with one `audio` field | After a 20 s timeout the client plays the error sound and accepts the next key press |
| FR-4 | Transcribe the question locally with faster-whisper `small.en` | WAV → question text | ≥ 90% of the 30 eval questions keep their meaning; ≤ 1 s each |
| FR-5 | Answer with the Gemini model from config (`gemini-3.5-flash-lite`) through `google-genai`: minimal thinking, 10 s timeout per call (the API minimum), API key from an environment variable, the tool functions (including `web_search`) in every request; `web_search(query)` runs on the server against the web search API (key from an environment variable, timeout from config) and its results go back to Gemini; answers ≤ 2 short sentences (under 40 words) except list answers (FR-8, FR-9) | Question text → answer text, `searched` flag | ≥ 80% of the 10 general and live eval questions correct; each Gemini call ≤ 10 s; `searched` is true in the log when `web_search` ran and returned results; a search API failure goes back to Gemini as an error result, not a crash; the LLM stage ends within its deadline (15 s, config): a Gemini or search call starts only if its full timeout fits in the time left, else 500 `{"error": "llm: deadline exceeded"}`; `web_search` sends only the search query to the search API, never note, reminder or memory content |
| FR-6 | Put the current date, weekday and time in the configured time zone (Asia/Kolkata) in the system instruction, so relative times become exact times | Clock → system instruction | With the clock fixed at Fri 9 Oct 2026 14:00 IST, the instruction contains that date, weekday and time; in the eval, "remind me tomorrow at 5 to call the lab" asked on 9 Oct gives `due_at` 2026-10-10T17:00+05:30 |
| FR-7 | Run Gemini's tool calls: execute each call, send the results back together with the model's previous content unchanged (including the `id` and `thought_signature`), repeat until Gemini returns text, at most 3 rounds | Function calls → tool results → final answer | A call followed by text runs the tool once and returns the answer; an unknown tool name or bad arguments goes back to Gemini as an error result, not a crash; more than 3 rounds gives 500 `{"error": "llm: too many tool rounds"}` |
| FR-8 | Notes tools: `add_note(text)` stores a note; `list_notes()` returns every note, newest first | Tool call → SQLite row / list | After `add_note`, the notes table has one new row with that text and its creation time; `list_notes` returns all notes newest first, or an empty list |
| FR-9 | Reminder tools: `add_reminder(text, due_at)` stores a pending reminder (`due_at` is ISO 8601 with offset); `list_reminders()` returns every pending reminder by due time with id, text and due time; `cancel_reminder(id)` cancels a pending reminder | Tool call → SQLite row / list / status change | `add_reminder` stores one pending row; a `due_at` in the past returns an error result and stores nothing; `list_reminders` excludes delivered and cancelled ones; `cancel_reminder` sets the status to cancelled, and an unknown or non-pending id returns an error result; the spoken list gives each reminder's date and time |
| FR-10 | Confirm every action by repeating it back with the stored values; on a tool error, say what went wrong | Tool result → answer text | In the eval, every passing notes and reminder answer names the action and its text, plus the time for reminders ("Reminder set for 5 pm tomorrow: call the lab") |
| FR-11 | Convert the answer to speech with Piper | Text → WAV, resampled to 16 kHz mono 16-bit | ≤ 1 s for a 40-word answer; every word understandable |
| FR-12 | List due reminders | `GET /reminders/due` → JSON or 204 | 200 with `[{id, text, due_at}]` of pending reminders with `due_at` ≤ now, oldest first; 204 with an empty body when none; future, delivered and cancelled reminders never listed; polling again without an ack returns the same reminders |
| FR-13 | Speak one reminder | `GET /reminders/{id}/audio` → WAV | Spoken text is "Reminder, 5 pm: call the lab" when due less than 60 s ago, "Missed reminder, 5 pm: call the lab" when due 60 s or more ago, with the date added when it was not today ("Missed reminder, 8 October, 5 pm: …"); unknown id gives 404 `{"error": "reminder not found"}` |
| FR-14 | Acknowledge a reminder | `POST /reminders/{id}/ack` → JSON | 200 `{"status": "ok"}` and the reminder is marked delivered; this is the only way a reminder becomes delivered (`/reminders/due` and `/reminders/{id}/audio` never change its status); it never appears in `/reminders/due` again; acking again gives 200; unknown id gives 404 `{"error": "reminder not found"}` |
| FR-15 | Client polls for due reminders every 10 s, never while recording or waiting for an answer; for each due reminder it prints the text, plays its audio, then acks it | Poll → printed text + sound | A reminder due while the client runs is heard within 10 s of its due time (or right after a query in progress); a reminder due while the client is closed is heard as a missed reminder within 10 s of the next start; a reminder is acked only after its audio has played |
| FR-16 | Handle errors without crashing the server | Bad input or failed stage → JSON error | 400 `{"error": "<reason>"}` when audio is missing, empty, not a WAV, or not 16 kHz mono 16-bit; 400 `{"error": "no speech detected"}` when the transcript is empty, before the LLM runs; 500 `{"error": "<stage>: <reason>"}` when a stage fails; the server answers the next request normally |
| FR-17 | Log every query on the server | Each `/query` → one JSONL line | Every query, failed ones included, writes one line with time, question, answer, per-stage timings, `searched`, tool calls (name, arguments, ok or error) and error; no API key or token ever appears in the log |
| FR-18 | Report health and stay local | `GET /health` → JSON | 200 `{"status": "ok", "model": "<model name>"}`; the server binds to the configured host 127.0.0.1, so another device on the same Wi-Fi gets no answer on the port |

## Interface contract

The client uses exactly this API. Freeze it before writing code. v2 reuses the reminder endpoints unchanged.

```text
POST /query                          # one question, one answer
  Content-Type: multipart/form-data
  audio : WAV file, 16 kHz mono 16-bit   # the question (FR-1), required

  200 OK          Content-Type: audio/wav      # answer audio (FR-11)
  400 Bad Request {"error": "<reason>"}        # audio missing, empty or unreadable, or no speech detected
  500 Server Error {"error": "<stage>: <reason>"}   # a stage failed

GET /reminders/due                   # FR-12
  200 OK  [{"id": 3, "text": "call the lab", "due_at": "2026-10-10T17:00:00+05:30"}]
  204 No Content                     # nothing due

GET /reminders/{id}/audio            # FR-13
  200 OK  Content-Type: audio/wav    # "Reminder, 5 pm: call the lab"
  404 Not Found {"error": "reminder not found"}

POST /reminders/{id}/ack             # FR-14
  200 OK  {"status": "ok"}
  404 Not Found {"error": "reminder not found"}

GET /health                          # FR-18
  200 OK  {"status": "ok", "model": "<model name>"}
```

The server listens on 127.0.0.1 and a fixed port from config. The client stores the server address and port in its config.

## Tool functions

Gemini sees these declarations. Times are ISO 8601 with the configured offset (+05:30).

| Tool | Arguments | Result sent back to Gemini |
| --- | --- | --- |
| `web_search` | `query` | `{results: [{title, url, content}]}` or `{error}` |
| `add_note` | `text` | `{id, text, created_at}` |
| `list_notes` | none | `{notes: [{id, text, created_at}]}` |
| `add_reminder` | `text`, `due_at` | `{id, text, due_at}` or `{error}` |
| `list_reminders` | none | `{reminders: [{id, text, due_at}]}` |
| `cancel_reminder` | `id` | `{id, text, due_at, status: "cancelled"}` or `{error}` |

To cancel by description ("cancel the lab reminder"), Gemini calls `list_reminders` and then `cancel_reminder` with the matching id, within the 3-round limit.

## Quality targets

v1 is done, and tagged v0.1.0, when every target below is met.

| Metric | Target | How measured |
| --- | --- | --- |
| Correctness | ≥ 80% in each group of 10 (general and live, notes, reminders) | Test plan below |
| Latency (key release → first answer audio) | ≤ 15 s, median over all 30 eval questions | Client timer + server stage timings (FR-17) |
| Transcription | ≥ 90% of questions keep their meaning | Logged question text vs the written question |
| Reliability | 20 queries in a row with no crash or restart | One continuous run |
| Due reminders | Heard within 10 s of due time; a missed one heard within 10 s of the next client start | FR-15 manual checks |
| Secrets | API key, `.env` and the database never in git; no key in any log | `.gitignore` check and a search of `logs/` |

Latency budget: STT 1 s + Gemini (one call for a plain answer, usually two for a live question or a tool command; 10 s timeout each, typically 2–4 s) + one web search call for a live question (5 s timeout) + TTS 1 s + playback start 1 s. The log shows which stage broke the budget.

Worst case: the LLM stage stops at its 15 s deadline (one Gemini call 10 s + search 5 s fits; a second Gemini call starts only if 10 s are left), so STT 1 s + LLM 15 s + TTS 1 s = 17 s, under the client's 20 s timeout. The server then returns a clean 500 before the client gives up.

## Test plan

pytest covers the server with Gemini, whisper and Piper faked and a temporary SQLite database. The evaluation below uses the real models.

1. Write all 30 rows in `tests/questions.csv` before the first run, then freeze it. Columns: id, group (general, notes, reminders), setup, question, expected.
   - setup: the notes and reminders that must exist before the question (for list and cancel commands), or "none".
   - expected: the answer for general questions; the tool name and arguments for tool questions, with times written relative to the run ("tomorrow 17:00") and resolved by `run_eval.py` at run time.
2. Run against a fresh evaluation database, never the real one.
3. Grading:
   - General and live: correct, partial or wrong, judged by me; live answers checked against a trusted website at test time. Only "correct" counts.
   - Notes and reminders: pass when the right tool is called with the right arguments, the database holds the expected result afterwards, and the answer repeats the action back (FR-10).
4. Report accuracy per group, median and worst latency, and transcription accuracy.
5. Re-run the whole set whenever the model, prompt or tool declarations change.

The home city for weather questions comes from the server config.

## Open decisions

- How the eval questions are spoken: live into the mic during `run_eval.py`, or recorded once as WAV files. Decide when planning M7.

## Decisions settled in Design

- [x] Answers: `gemini-3.5-flash-lite` with function calling; live information through a `web_search` tool backed by a web search API (Google Search grounding has no API quota on our free tier)
- [x] Speech-to-text: faster-whisper `small.en`, local
- [x] Text-to-speech: Piper, local, 16 kHz output
- [x] Storage: one SQLite file on the laptop, gitignored
- [x] Server: FastAPI, one process, models loaded once at startup, bound to 127.0.0.1
