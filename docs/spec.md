Version 3. See roadmap.md.

# AI Assistant v3 Spec: Memory

Updated Oct 20, 2026 · Bhavik Fulfagar

v3 adds memory to the v2 study assistant. A profile of fixed slots (who I am, my goals, how
I want answers) is in every prompt, and short memory items outlive the 120 s session and are
recalled by question. Everything stays on the laptop except the Gemini and search calls.
Scope and out-of-scope items are in brief.md.

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

Profile flow: the server loads `data/profile.json` at startup and puts the whole profile
in the system instruction of every Gemini call.

Memory flow: memory commands and recall go through tool functions. The server searches the
memory table locally and passes at most 5 items to Gemini. When a session ends, a writer
call keeps 0 to 3 key points.

Reminder flow: every 10 s the client asks `GET /reminders/due`. For each due reminder it
prints the text, fetches and plays its audio, then acknowledges it. A reminder stays due
until acknowledged, so none is lost if the client is closed.

## Functional requirements

Each ID later becomes one or more build tasks and tests. Fixed values (rates, timeouts,
intervals, limits, sizes, model name, time zone) live in config files. FR-1 to FR-18 keep
their v1 IDs and FR-19 to FR-25 their v2 IDs; a changed one is marked "(changed in v3)".
FR-26 onwards are new in v3.

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

### FR-17 (changed in v2 and v3)

- Requirement: Log every query on the server
- Input → Output: Each `/query` → one JSONL line
- Acceptance: Every query, failed ones included, writes one line with time, question,
  answer, per-stage timings, `searched`, tool calls and error. Each tool call records its
  name, arguments and whether it ran ok, failed, or was refused for lack of time (issue
  #59). The line also records whether an image was sent (yes or no, never the image),
  whether a session was continued, and any concept logged. From v3 it also records how many
  memory items were passed to Gemini and how many profile lines were rendered, never their
  text, and the session writer writes one line of its own on the reminder poll (FR-39). No
  API key or token ever appears in the log

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

### FR-26 Profile schema

- Requirement: The profile's slots are defined in `config/profile_schema.json`, not in code.
  Each slot has a name, a one-line description and the question asked for it at setup.
  Changing the file changes the slots with no Python change, so a different kind of user
  gets a different profile. The default schema has ten slots: identity, goal_now, goal_mid,
  goal_long, interests, exploring, understanding, skillset, style, constraints
- Input → Output: Schema file → the slots the assistant knows about
- Acceptance: Adding a slot to the schema file and restarting makes the server accept and
  store a value for it; removing a slot stops it reaching the prompt; a malformed schema
  file fails at startup with a clear message, not at the first query

### FR-27 Profile values

- Requirement: Profile values live in `data/profile.json`, one line per slot, readable and
  editable by hand. A value a slot has no schema entry for is ignored with a logged warning,
  not an error. An empty slot is allowed
- Input → Output: Values file → the profile the assistant holds
- Acceptance: Editing the file by hand and restarting changes what the assistant knows; a
  missing file starts an empty profile and does not crash; a value for an unknown slot is
  ignored and logged

### FR-28 Profile in every prompt

- Requirement: The whole profile goes into the system instruction of every Gemini call,
  including the writer call. It is capped at `PROFILE_MAX_LINES` (40) **rendered** lines —
  the lines that enter the instruction, not lines in the file. The cap is checked at load
  and at every write. Going over it is an error, not a silent truncation
- Input → Output: Profile → part of every system instruction
- Acceptance: A query made with a filled profile has every non-empty slot in the request
  (fake client); a profile rendering 41 lines fails at load with a clear message naming the
  cap; a confirmed `update_profile` or setup answer that would take the rendered profile
  over the cap is refused, the caller is told, and the stored profile is unchanged; a file
  whose length differs from what it renders - an empty slot renders nothing, a long value
  renders as several lines - is measured by what it renders;
  an empty profile adds nothing to the instruction

### FR-29 First-run setup

- Requirement: When `data/profile.json` is missing or empty, the next question starts
  setup instead: the assistant asks the six setup slots in schema order (identity, goal_now,
  goal_long, exploring, style, constraints), one per key press, and writes the answers to
  the file. The other slots stay empty. Setup can be left by saying "stop setup"; what was
  answered is kept
- Input → Output: Spoken answers → `data/profile.json`
- Acceptance: With no profile file, the first query is answered with the first setup
  question, not a normal answer; six answers fill six slots in the file and the seventh
  query is answered normally; "stop setup" leaves setup and keeps the slots already
  answered; in the eval, six spoken answers fill all six slots correctly

### FR-30 Stale goal check

- Requirement: `goal_now` carries the date it was set. When it is more than
  `GOAL_STALE_DAYS` (31) days old, the assistant adds one line to its next answer saying the
  month goal may be out of date and asking whether it still holds. It says this at most once
  per session and never edits the goal itself
- Input → Output: Stale `goal_now` → one extra line in one answer
- Acceptance: With `goal_now` set 32 days ago, the next answer carries the line and the
  following answer in the same session does not; with it set 30 days ago, no line; the
  stored goal and its date are unchanged either way

### FR-31 Slot update proposals

- Requirement: The assistant may propose a profile change ("you have mentioned interviews
  three times, should I update your month goal?") and must have a yes before writing. It
  never edits a slot on its own. A proposal the user declines is not proposed again in the
  same session
- Input → Output: Proposal → a write only after a yes
- Acceptance: A declined proposal writes nothing and is not repeated in that session; an
  accepted one writes the slot and speaks back what it wrote; no code path writes a slot
  without a yes, setup (FR-29) excepted

### FR-32 Memory item

- Requirement: A memory item is one key point of at most `MEMORY_MAX_WORDS` (12) words, with
  a type (fact, project, preference, session), the date it was stored, and its text. Never a
  transcript. Stored in SQLite in the same database as notes, reminders and concepts
- Input → Output: Key point → memory row
- Acceptance: A stored item has all four fields set; an item over the word limit is rejected
  before storage and the caller is told; the table survives a restart

### FR-33 Remember that

- Requirement: "Remember that ..." stores exactly one item and speaks it back so the user
  can hear what was stored. Gemini shortens the spoken sentence to a key point within the
  word limit and picks the type
- Input → Output: "Remember that ..." → one row, spoken confirmation
- Acceptance: One command stores exactly one row, never two; the spoken answer contains the
  stored text; in the eval, 10 commands are stored correctly (within the word limit, right
  type) in at least 9 cases

### FR-34 Forget

- Requirement: "Forget ..." deletes the one matching item and nothing else. When more than
  one item matches, the assistant names them and asks which, and deletes nothing until
  answered. When nothing matches, it says so
- Input → Output: "Forget ..." → one deletion, or a question
- Acceptance: With one match, that row is gone and every other row remains; with two
  matches, nothing is deleted and the answer names both; answering the question then deletes
  only the named one; with no match, nothing is deleted and the answer says so; in the eval,
  5 of 5 forget cases delete the right row and only that row

### FR-35 Wipe

- Requirement: "Wipe my memories" does not wipe. It asks back for the exact phrase
  `WIPE_CONFIRM_PHRASE` ("yes wipe everything"). Only an exact match, ignoring case and
  trailing punctuation, wipes every memory item. Anything else cancels. The profile is not
  touched
- Input → Output: "Wipe my memories" → a confirmation question, then a wipe or a cancel
- Acceptance: The first command deletes nothing; the exact phrase then deletes every memory
  row and leaves notes, reminders, concepts and the profile intact; a near miss ("yes wipe
  it all") deletes nothing and says it was cancelled; the confirmation does not survive into
  the next session

### FR-36 List memories

- Requirement: "List my memories" speaks up to `MEMORY_LIST_MAX` (5) items, most recent
  first, and the total count when there are more
- Input → Output: Question → spoken list
- Acceptance: With 8 items the answer names the 5 most recent and gives the total; with none
  it says so; the answer follows the FR-5 limit

### FR-37 Recall (changed backend in v3)

- Requirement: Recall goes through one interface,
  `search_memories(query, k, since=None, until=None)`, so the ranking backend can be
  replaced without touching its callers. v3 implements it with SQLite
  FTS5 full-text search, which adds no dependency. At most `MEMORY_RECALL_MAX` (5) items
  reach Gemini. The whole store is never sent, to any model or any tool
- Input → Output: Question → at most 5 items in the Gemini request
- Acceptance: A recall question sends at most 5 items (fake client); with 50 items stored,
  the request still carries at most 5; no code path puts the full store in a request or in a
  `web_search` query; replacing the search implementation behind the interface needs no
  change in its callers; in the eval, the right memory is in the top 5 for at least 90% of
  20 recall questions and the spoken answer is correct for at least 17 of 20

### FR-38 Time filter

- Requirement: A question naming a time ("last week", "yesterday", "in September") filters
  candidates by date before ranking, between `since` and `until`. A bound given as a date
  only is interpreted as midnight in the configured time zone, not UTC. A question naming no
  time searches everything
- Input → Output: Question with a time → date-filtered search
- Acceptance: With one matching item inside the named window and one outside it, only the
  one inside is returned, whether the outside one is before `since` or after `until`; the
  same question without the time returns both; an item stored at 02:00 local time on a day
  is inside a `since` bound naming that day; an unparseable `since` or `until` falls back
  to searching everything rather than returning nothing

### FR-39 Session writer

- Requirement: When a session ends, one Gemini call reviews it and keeps 0 to 3 key points.
  It applies a salience rule: keep only what would still matter in a month. It decides
  whether a point is worth keeping before deciding how to word it. The assistant speaks only
  how many it kept ("Noted two things."), never the contents. A failed writer call is logged
  and loses the points; it never fails the user's query
- Input → Output: Ended session → 0 to 3 rows, a spoken count
- Acceptance: A session of small talk keeps 0 points and says nothing; a session with three
  durable facts keeps up to 3; the spoken line gives the count and no content; a writer call
  that errors leaves the store unchanged and is logged; in the eval, at least 7 of 10
  sessions produce points judged useful by the rule in brief.md, and after 10 sessions the
  store holds no more than 15 items

### FR-40 No over-merge

- Requirement: The writer and `remember that` never merge a new item onto an existing one
  unless it is the same thing. `find_same` is a safety guard, not a deduplicator. At
  `MEMORY_SAME_THRESHOLD` 0.9 it collapses only near-verbatim repeats; a paraphrase, a
  synonym or an added word is stored as a second row. Merging those is compaction, which is
  v4. Reusing an existing item's wording for a different point is a failure, not a tidy-up.
  This is the v2 concept logger's failure mode (issue #116), where "attention in
  transformers" and "overfitting" were both filed under the existing name "lora fine-tuning"
- Input → Output: A new point near an existing one → a new row, not a merge
- Acceptance: With "LoRA fine-tuning" already stored, storing "attention in transformers"
  adds a new row and leaves the first unchanged; storing a near-verbatim repeat - the same
  point with the same content words - adds no row, leaves the stored item unchanged, and
  reports it back as already remembered; a paraphrase that changes content words is
  expected to add a row; in the eval, 0 of 5 near-miss pairs are merged

## Interface contract

The client uses exactly this API. It is frozen. v2 adds only the optional `image` field, two
400 errors and `POST /session/reset`; the reminder endpoints and `/health` are unchanged. v3
adds no endpoint and no field: the profile and memory are server-side and reach Gemini
through the system instruction and the tool functions.

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

v3 is done, and tagged v0.3.0, when every target below is met. The v3 recall set is frozen
after its first run, as in v1 and v2.

| Metric | Target | How measured |
| --- | --- | --- |
| Recall, right memory in top 5 (FR-37) | ≥ 90% | 20 recall questions, seeded store |
| Recall, answer correct (FR-37) | ≥ 17 of 20 | The same 20 questions |
| Remember that (FR-33) | ≥ 9 of 10 stored correctly | 10 spoken commands |
| Forget (FR-34) | 5 of 5 right row and only that row | 5 forget cases |
| Invented memories (FR-37) | 0 of 10 | 10 questions about things never stated |
| Over-merge (FR-40) | 0 of 5 pairs merged | 5 near-miss pairs |
| Profile setup (FR-29) | 6 of 6 slots filled correctly | One setup run, 6 spoken answers |
| Store growth (FR-39) | ≤ 15 items after 10 sessions | Count after the writer runs 10 times |
| Auto-writer usefulness (FR-39) | ≥ 7 of 10 sessions | The scoring rule in brief.md |
| Latency | ≤ 5.3 s median | Client timer + stage timings |
| Regression | v1 and v2 targets met | Re-runs of both eval sets |

The 5.3 s latency target is the v2 Look median of 4.3 s measured on this machine on
2026-10-20, plus 1 s. It is not derived from the old laptop.

Regression: a re-run of the v1 eval meets every v1 target except transcription, which must
be no worse than 26 of 30 (issue #38); a re-run of the v2 eval meets every v2 target except
concept logging, which is known to be flaky and must be no worse than 17 of 20 (issue #116).

Latency budget and worst case are as in v1 (FR-5). v3 adds a local search before the Gemini
call and a longer system instruction; neither uses the GPU. The writer call happens after
the answer has been spoken and is outside the user's latency path.

## Test plan

pytest covers the server with Gemini, whisper and Piper faked, and a temporary SQLite
database. The evaluation below uses the real models.

1. Write the v3 recall set before its first run, then freeze it (only an obvious error in a
   question may be fixed, logged in plan.md). It holds a seeded store, 20 recall questions,
   10 remember commands, 5 forget cases, 10 questions about things never stated, 5 near-miss
   pairs and one setup run of 6 answers. Each row has a pass rule.
   - The seeded store is the eval's own, never `data/assistant.db`.
   - Spoken questions are recorded once as WAV files, not in git, as in v1.
2. Call `POST /session/reset` before each question (FR-22).
3. Run against a clean state, with notes, reminders, concepts, memories and the profile
   backed up and restored, as in v1 and v2. Pace the calls to stay under 15 Gemini requests
   per minute. The writer adds one call per session, so budget for it against the 500-a-day
   limit.
4. Grading:
   - Recall: pass when the expected item is in the 5 sent to Gemini, and separately when the
     spoken answer is correct.
   - Remember: pass when one row is stored, within the word limit, right type.
   - Forget: pass when the named row is gone and every other row remains.
   - Invented memories: pass when the answer says it does not know, and fails when it states
     something that was never stored.
   - Over-merge: pass when the near-miss pair ends as two rows.
   - Setup: pass when each of the six slots holds what was said.
   - Auto-writer: scored against the rule in brief.md, immediately after each session, never
     batched.
5. The 10 writer sessions run as their own phase, after the question rows and with no
   `POST /session/reset` between them. The writer fires on the reminder poll when a session
   expires, so each session must be allowed to lapse its 120 s TTL before the poll is
   called. Budget about 20 minutes of wall clock for this phase.
6. `MEMORY_SAME_THRESHOLD` is tuned against its own pairs, written for the M13 spike and
   never placed in `questions_v3.json`. Tuning it on the five near-miss pairs the eval then
   scores would make that target measure nothing.
7. Report per-group accuracy, median and worst latency, store size after the 10 writer
   sessions, and the results of both regression re-runs.
8. Re-run the whole set whenever the model, prompt, tool declarations or the search
   implementation change.

The home city for weather questions comes from the server config.

## Open decisions

- Whether to add a local embedding model behind the FR-37 interface. Decided after the first
  recall run: if "right memory in top 5" is below 90%, the failing questions decide it.
  Until then v3 adds no dependency.

## Decisions settled in Design

- [x] How the profile reaches the system instruction, and where the 40-line cap is enforced
- [x] Where `config/` sits in the project structure, and whether CLAUDE.md's structure
      section is updated in the same change
- [x] Whether memory commands and recall are tool functions or server logic
- [x] The FTS5 table design, and how items are tokenised for search
- [x] What counts as a session ending, and what triggers the writer call
- [x] How setup (FR-29) interrupts the normal query path
- [x] How the eval seeds its store and near-miss pairs
