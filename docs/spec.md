Version 2. See roadmap.md.

# AI Assistant v2 Spec: Teacher

Updated Oct 14, 2026 · Bhavik Fulfagar

v2 adds a study mode to the v1 voice assistant. Right Alt asks by voice as in v1. Right Ctrl
asks about what is on the screen: one screenshot goes to Gemini with the question. Follow-ups
work for 120 s after an answer. Learning questions are logged as concepts, "quiz me" asks
about them and grades each answer, and "what did I learn this week?" lists the new ones.
Everything stays on the laptop except the Gemini and search calls. Scope and out-of-scope
items are in brief.md.

## How it works

A Python client and a FastAPI server run on the same laptop. The server binds to 127.0.0.1.

User flow, push-to-talk:

1. The user holds Right Alt (voice only) or Right Ctrl (Look). The client plays the start
   sound and records. For Look, the client also takes one screenshot at key press.
2. The user releases the key. The client plays the thinking sound and sends the audio, and
   for Look the screenshot, to `POST /query`.
3. The server transcribes the question and sends it to Gemini with the recent session turns,
   the most recent image and the tool functions. Gemini may call `web_search`, the notes and
   reminder tools, or both; the server runs each call (web search API or SQLite) and returns
   the results to Gemini until it gives a final answer. A learning question is also logged as
   a concept.
4. The server turns the answer into speech and returns the WAV.
5. The client plays the answer, or the error sound on failure.

Session flow: the server keeps the last 5 turns and the most recent image in memory. A
follow-up or "tell me more" within 120 s of the last answer uses them.

Quiz flow: "quiz me" starts a quiz of up to 3 concepts. Each key press after a question is
the answer; the server grades it in one line and asks the next question, then speaks the
score.

Reminder flow: every 10 s the client asks `GET /reminders/due`. For each due reminder it
prints the text, fetches and plays its audio, then acknowledges it. A reminder stays due
until acknowledged, so none is lost if the client is closed.

## Functional requirements

Each ID later becomes one or more build tasks and tests. Fixed values (rates, timeouts,
intervals, limits, sizes, model name, time zone) live in config files. FR-1 to FR-18 keep
their v1 IDs; a changed one is marked "(changed in v2)". FR-19 onwards are new in v2.

### FR-1 (changed in v2)

- Requirement: Record the question while the voice key is held, 10 s max. The voice key is
  Right Alt (it replaces F9); the key is set in `client_pc/config.py`.
- Input → Output: Key hold → WAV, 16 kHz mono 16-bit
- Acceptance: Speech clear on playback in 20 of 20 tests; recording stops at release or at
  10 s

### FR-2

- Requirement: Play status sounds: start sound on key press, thinking sound after release,
  error sound on any failure
- Input → Output: Client events → sounds
- Acceptance: The user can tell the state without a screen; the error sound plays on a 400,
  a 500, a timeout and a refused connection

### FR-3 (changed in v2)

- Requirement: Send the question to the server with a 25 s client timeout
- Input → Output: WAV, and for Look an image (FR-19) → `POST /query` with an `audio` field
  and an optional `image` field
- Acceptance: After a 25 s timeout the client plays the error sound and accepts the next
  key press

### FR-4

- Requirement: Transcribe the question locally with faster-whisper `small.en`
- Input → Output: WAV → question text
- Acceptance: ≥ 90% of the 30 eval questions keep their meaning; ≤ 1 s each

### FR-5 (changed in v2)

- Requirement: Answer with the Gemini model from config (`gemini-3.5-flash-lite`) through
  `google-genai`: minimal thinking, 10 s timeout per call (the API minimum), API key from an
  environment variable, the tool functions (including `web_search`) in every request;
  `web_search(query)` runs on the server against the web search API (key from an environment
  variable, timeout from config) and its results go back to Gemini; answers at most 3
  sentences and at most 60 words, except list answers (FR-8, FR-9 and others), which may
  have up to 5 items; a list of more than 5 items says the total count and the first 5
  (newest notes, soonest reminders), and "tell me more" gives the next 5; "tell me more"
  follows the same limit
- Input → Output: Question text → answer text, `searched` flag
- Acceptance: ≥ 80% of the 10 general and live eval questions correct; each Gemini call
  ≤ 10 s; `searched` is true in the log when `web_search` ran and returned results; a search
  API failure goes back to Gemini as an error result, not a crash; the LLM stage ends within
  its deadline (15 s, config): a Gemini call starts only if its full timeout fits in the time
  left; the first search always runs; a tool round after the first runs only if elapsed + its
  tool timeout (0 s for notes and reminders, 5 s for `web_search`) + 10 s <= 18 s
  (`LLM_FINAL_DEADLINE_S`, config), and a refused tool call goes back to Gemini as an error
  result ("no time left"). When the deadline stops the model, the server makes one last
  Gemini call that may not call tools, using what the tools returned, if elapsed <= 8 s
  (`LLM_FINAL_START_MAX_S`, config), and speaks that answer; only if that is not possible or
  fails, 500 `{"error": "llm: deadline exceeded"}`; `web_search` sends only the search query
  to the search API, never note, reminder or memory content

### FR-6

- Requirement: Put the current date, weekday and time in the configured time zone
  (Asia/Kolkata) in the system instruction, so relative times become exact times
- Input → Output: Clock → system instruction
- Acceptance: With the clock fixed at Fri 9 Oct 2026 14:00 IST, the instruction contains
  that date, weekday and time; in the eval, "remind me tomorrow at 5 to call the lab" asked
  on 9 Oct gives `due_at` 2026-10-10T17:00+05:30

### FR-7

- Requirement: Run Gemini's tool calls: execute each call, send the results back together
  with the model's previous content unchanged (including the `id` and `thought_signature`),
  repeat until Gemini returns text, at most 3 rounds
- Input → Output: Function calls → tool results → final answer
- Acceptance: A call followed by text runs the tool once and returns the answer; an unknown
  tool name or bad arguments goes back to Gemini as an error result, not a crash; more than
  3 rounds gives 500 `{"error": "llm: too many tool rounds"}`; when the deadline (FR-5)
  stops the rounds, the last call without tools gives the answer instead of the 500; a
  list-then-cancel command runs both rounds

### FR-8

- Requirement: Notes tools: `add_note(text)` stores a note; `list_notes()` returns every
  note, newest first
- Input → Output: Tool call → SQLite row / list
- Acceptance: After `add_note`, the notes table has one new row with that text and its
  creation time; `list_notes` returns all notes newest first, or an empty list

### FR-9

- Requirement: Reminder tools: `add_reminder(text, due_at)` stores a pending reminder
  (`due_at` is ISO 8601 with offset); `list_reminders()` returns every pending reminder by
  due time with id, text and due time; `cancel_reminder(id)` cancels a pending reminder
- Input → Output: Tool call → SQLite row / list / status change
- Acceptance: `add_reminder` stores one pending row; a `due_at` in the past returns an error
  result and stores nothing; `list_reminders` excludes delivered and cancelled ones;
  `cancel_reminder` sets the status to cancelled, and an unknown or non-pending id returns
  an error result; the spoken list gives each reminder's date and time

### FR-10

- Requirement: Confirm every action by repeating it back with the stored values; on a tool
  error, say what went wrong
- Input → Output: Tool result → answer text
- Acceptance: In the eval, every passing notes and reminder answer names the action and its
  text, plus the time for reminders ("Reminder set for 5 pm tomorrow: call the lab")

### FR-11

- Requirement: Convert the answer to speech with Piper
- Input → Output: Text → WAV, resampled to 16 kHz mono 16-bit
- Acceptance: ≤ 1 s for a 40-word answer; every word understandable

### FR-12

- Requirement: List due reminders
- Input → Output: `GET /reminders/due` → JSON or 204
- Acceptance: 200 with `[{id, text, due_at}]` of pending reminders with `due_at` ≤ now,
  oldest first; 204 with an empty body when none; future, delivered and cancelled reminders
  never listed; polling again without an ack returns the same reminders

### FR-13

- Requirement: Speak one reminder
- Input → Output: `GET /reminders/{id}/audio` → WAV
- Acceptance: Spoken text is "Reminder, 5 pm: call the lab" when due less than 60 s ago,
  "Missed reminder, 5 pm: call the lab" when due 60 s or more ago, with the date added when
  it was not today ("Missed reminder, 8 October, 5 pm: …"); unknown id gives 404
  `{"error": "reminder not found"}`

### FR-14

- Requirement: Acknowledge a reminder
- Input → Output: `POST /reminders/{id}/ack` → JSON
- Acceptance: 200 `{"status": "ok"}` and the reminder is marked delivered; this is the only
  way a reminder becomes delivered (`/reminders/due` and `/reminders/{id}/audio` never change
  its status); it never appears in `/reminders/due` again; acking again gives 200; unknown id
  gives 404 `{"error": "reminder not found"}`

### FR-15

- Requirement: Client polls for due reminders every 10 s, never while recording or waiting
  for an answer; for each due reminder it prints the text, plays its audio, then acks it
- Input → Output: Poll → printed text + sound
- Acceptance: A reminder due while the client runs is heard within 10 s of its due time (or
  right after a query in progress); a reminder due while the client is closed is heard as a
  missed reminder within 10 s of the next start; a reminder is acked only after its audio
  has played

### FR-16 (changed in v2)

- Requirement: Handle errors without crashing the server
- Input → Output: Bad input or failed stage → JSON error
- Acceptance: 400 `{"error": "<reason>"}` when audio is missing, empty, not a WAV, or not
  16 kHz mono 16-bit; 400 `{"error": "image is not a readable image"}` when an `image` is
  sent that cannot be read as JPEG or PNG; 400 `{"error": "image too large"}` when it is
  over 2 MB; both image checks run before any stage; 400 `{"error": "no speech detected"}`
  when the transcript is empty, before the LLM runs; 500 `{"error": "<stage>: <reason>"}`
  when a stage fails; the server answers the next request normally

### FR-17 (changed in v2)

- Requirement: Log every query on the server
- Input → Output: Each `/query` → one JSONL line
- Acceptance: Every query, failed ones included, writes one line with time, question,
  answer, per-stage timings, `searched`, tool calls and error. Each tool call records its
  name, arguments and whether it ran ok, failed, or was refused for lack of time (issue
  #59). The line also records whether an image was sent (yes or no, never the image),
  whether a session was continued, and any concept logged. No API key or token ever appears
  in the log

### FR-18

- Requirement: Report health and stay local
- Input → Output: `GET /health` → JSON
- Acceptance: 200 `{"status": "ok", "model": "<model name>"}`; the server binds to the
  configured host 127.0.0.1, so another device on the same Wi-Fi gets no answer on the port

### FR-19 Look key

- Requirement: Right Ctrl records voice like Right Alt (FR-1) and takes one screenshot of
  the screen at key press. The client shrinks it to a longest side of 1280 px, encodes it as
  JPEG and sends it with the audio. Screenshots are never saved to disk. The key is set in
  `client_pc/config.py`
- Input → Output: Key hold → WAV + one JPEG
- Acceptance: With a fake screen grab, the request carries one JPEG whose longest side is
  at most 1280 px; the screenshot is taken at press, not at release; Right Alt sends no
  image; no image file is written anywhere

### FR-20 /query image

- Requirement: `POST /query` accepts an optional multipart field `image` (JPEG or PNG, at
  most 2 MB). The image is sent to Gemini with the question. Without an image, `/query`
  behaves as in v1
- Input → Output: `audio` + optional `image` → answer WAV
- Acceptance: With an image, the Gemini request contains it next to the question (fake
  client); without one, the request matches v1; an unreadable or oversized image gives the
  400 errors of FR-16; the log records that an image was sent, never the image

### FR-21 Sessions

- Requirement: The server keeps one session (single user) with the last 5 question and
  answer pairs and the most recent image, in memory only. It ends 120 s after the last
  answer. Follow-up questions and "tell me more" use it
- Input → Output: Turns + image → context for the next question
- Acceptance: A follow-up asked within 120 s of the last answer is answered with the earlier
  turns and image as context ("what is it used for?" after "what is LoRA?"); after 120 s the
  same follow-up is answered as a new question; restarting the server clears the session;
  "tell me more" gives one more short answer within the FR-5 limit; the log shows that a
  session was continued

### FR-22 Session reset

- Requirement: `POST /session/reset` clears the session and any running quiz. The eval calls
  it before each question
- Input → Output: `POST /session/reset` → JSON
- Acceptance: 200 `{"status": "ok"}`; the next question has no earlier turns, no image and no
  quiz running; calling it with no session is also 200

### FR-23 Concepts

- Requirement: Learning questions (for example, "what is LoRA?") are logged as concepts;
  other questions (for example, "when is Diwali?") are not. A concept has a short name, a
  one-line summary, the date first asked, the date last asked, a status (new, right, wrong)
  and the date last quizzed. Gemini reuses an existing concept name when it is the same
  concept, so the row is updated instead of duplicated. No embeddings. Stored in SQLite
- Input → Output: Question → concept row
- Acceptance: Asking "what is LoRA?" adds one row with status new and the first-asked and
  last-asked dates set; asking about LoRA again updates that row and adds none; "when is
  Diwali?" adds none; the log line names any concept logged (FR-17); in the eval, concepts
  are logged or skipped correctly for ≥ 90% of 20 questions

### FR-24 Quiz me

- Requirement: On request only ("quiz me"). Picks up to 3 concepts: status new first (oldest
  first), then status wrong (oldest last quizzed first). Asks one question per key press;
  during a quiz, my next key press is always taken as the answer; it grades the answer in
  one line (right or wrong plus a short correction) and asks the next question, then ends
  with the score ("2 of 3 right"). A graded concept gets status right or wrong, and the date
  last quizzed is set; no concept is ever deleted. While a quiz runs, the session waits up
  to 5 minutes for each answer; if no answer comes, the quiz ends quietly and that concept
  keeps its old status. "Stop quiz" ends it. With nothing to quiz, it says so
- Input → Output: "Quiz me" → questions, one-line grades, score
- Acceptance: With 4 new concepts and 1 wrong one, the quiz asks the 3 oldest new ones; with
  only wrong concepts, it asks the oldest last quizzed first; during a quiz, any press other
  than "stop quiz" is graded as the answer, even if it sounds like a question; after 5
  minutes without an answer the quiz ends with no sound and the concept's status is
  unchanged; each answer gets one line of right or wrong plus a correction; the end speaks
  the score; a concept answered right is not asked in a later
  quiz, a concept answered wrong is; "stop quiz" ends the quiz and keeps the statuses so far;
  with no concept to quiz it says so; no quiz starts unless asked; in the eval, grading
  agrees with my own judgement for ≥ 8 of 10 answers

### FR-25 Learned this week

- Requirement: "What did I learn this week?" speaks the number of concepts first asked in
  the last 7 days and up to 5 of their names; when there are more than 5, the 5 most recent
- Input → Output: Question → spoken list
- Acceptance: With 7 concepts first asked in the last 7 days and 2 older ones, the answer
  gives the count 7 and the names of the 5 most recent; with none, it says so; the answer
  follows the FR-5 limit

## Interface contract

The client uses exactly this API. It is frozen. v2 adds only the optional `image` field, two
400 errors and `POST /session/reset`; the reminder endpoints and `/health` are unchanged.

```text
POST /query                          # one question, one answer
  Content-Type: multipart/form-data
  audio : WAV file, 16 kHz mono 16-bit   # the question (FR-1), required
  image : JPEG or PNG, at most 2 MB      # the screenshot (FR-19, FR-20), optional

  200 OK          Content-Type: audio/wav      # answer audio (FR-11)
  400 Bad Request {"error": "<reason>"}
      # audio missing, empty or unreadable, or no speech detected
      # "image is not a readable image", "image too large"
  500 Server Error {"error": "<stage>: <reason>"}   # a stage failed

POST /session/reset                  # FR-22
  200 OK  {"status": "ok"}

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

The server listens on 127.0.0.1 and a fixed port from config. The client stores the server
address and port in its config.

## Tool functions

Gemini sees these declarations. Times are ISO 8601 with the configured offset (+05:30).

| Tool | Arguments | Result sent back to Gemini |
| --- | --- | --- |
| `web_search` | `query` | `{results: [{title, url, content}]}` or `{error}` |
| `add_note` | `text` | `{id, text, created_at}` |
| `list_notes` | none | `{notes: [{id, text, created_at}]}` |
| `add_reminder` | `text`, `due_at` | `{id, text, due_at, due_spoken}` or `{error}` |
| `list_reminders` | none | `{reminders: [{id, text, due_at, due_spoken}]}` |
| `cancel_reminder` | `id` | `{id, text, due_at, status: "cancelled"}` or `{error}` |

To cancel by description ("cancel the lab reminder"), Gemini calls `list_reminders` and then
`cancel_reminder` with the matching id, within the 3-round limit.

How concepts, the quiz and the weekly list (FR-23 to FR-25) reach Gemini is decided in
design.md.

## Quality targets

v2 is done, and tagged v0.2.0, when every target below is met. The v2 eval set is frozen
after its first run, as in v1.

| Metric | Target | How measured |
| --- | --- | --- |
| Look (FR-19, FR-20) | ≥ 80% correct | 20 saved screenshots with questions |
| Follow-ups (FR-21) | ≥ 8 of 10 understood | 10 follow-up cases |
| Concept logging (FR-23) | ≥ 90% logged or skipped correctly | 20 questions |
| Quiz grading (FR-24) | ≥ 8 of 10 agree with my judgement | 10 spoken answers |
| Latency, Look questions | ≤ 8 s median | Client timer + stage timings |
| Regression | v1 targets met; transcription ≥ 26 of 30 | Re-run of the v1 eval |

Regression: a re-run of the v1 eval meets every v1 target except transcription, which must
be no worse than v1's 26 of 30.

Latency budget and worst case are as in v1 (FR-5). An image adds screenshot capture, resize
and upload on the client and image input on the Gemini call. The log shows which stage broke
the budget.

## Test plan

pytest covers the server with Gemini, whisper and Piper faked, a fake screen grab and a
temporary SQLite database. The evaluation below uses the real models.

1. Write the v2 eval set before its first run, then freeze it (only an obvious error in a
   question may be fixed, logged in plan.md). It holds 20 Look questions with saved
   screenshots, 10 follow-up cases, 20 concept questions and 10 quiz answers I have judged
   right or wrong myself. Each row has a pass rule.
   - The eval keeps its own saved screenshots; the product never saves one.
   - Spoken questions are recorded once as WAV files, not in git, as in v1.
2. Call `POST /session/reset` before each question (FR-22), so rows do not leak context into
   each other. Follow-up cases run as sequences inside one session.
3. Run against a clean evaluation state, with the notes, reminders and concepts backed up
   and restored, as in v1. Pace the calls to stay under 15 Gemini requests per minute.
4. Grading:
   - Look: pass on the expected content of the answer for that screenshot.
   - Follow-ups: pass when the answer uses the earlier turn or image.
   - Concept logging: pass when the concept is logged or skipped as expected, with no
     duplicate row.
   - Quiz: the grade (right or wrong) is compared with my own judgement.
5. Report accuracy per group, median and worst latency for Look questions, and the result of
   the v1 eval re-run.
6. Re-run the whole set whenever the model, prompt or tool declarations change.

The home city for weather questions comes from the server config.

## Open decisions

None.

## Decisions settled in Design

- [ ] How concepts, the quiz and the weekly list reach Gemini (tools or server logic)
- [ ] How "quiz me" and "stop quiz" are detected
- [ ] How the image is passed to Gemini and kept in the session
- [ ] Screenshot library and JPEG quality
