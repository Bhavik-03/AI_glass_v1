# Roadmap

Updated Oct 14, 2026 · Bhavik Fulfagar

## Final goal

A learning companion and assistant for an engineering student, worn as glasses: it sees
what I study, answers in a few short sentences, tracks what I am learning and quizzes me,
remembers me, and helps me run my day and my habits.

- Single user (me), no accounts.
- Voice in, voice out. Nothing is shown on a screen (no AR display).
- "Look" sends one image with the question: a screenshot on the laptop now, a camera
  frame on the glasses later. Never video.
- Answers are 1 to 3 short sentences; "tell me more" gives one more short layer.
- A free cloud API (Gemini) first. Open-source models replace a part later only when
  the eval shows they are at least as good.
- A prototype, not a product: each version is the smallest useful thing and ends with
  a measured eval.

## Process rule

- Only the current version has detailed docs: `brief.md`, `spec.md`, `design.md` and
  `plan.md` in `docs/`.
- At the end of a version: copy them to `docs/archive/vN/`, tag the release, then write
  the next version's docs.
- Milestone IDs continue across versions (v1 ended at M7, so v2 starts at M8).
- This roadmap replaced the phone-link-first roadmap on Oct 14, 2026.

## v1 Voice assistant · tag v0.1.0 · done

- Hold one key, ask a general or live question, add or list notes, set, list or cancel
  reminders, hear due reminders. Laptop client and local server (127.0.0.1).
- Pipeline: faster-whisper `small.en` → Gemini Flash-Lite with tools (Tavily web search,
  notes, reminders in SQLite) → Piper TTS.
- Results (Oct 11, 2026): general 8/10, notes 10/10, reminders 10/10, median 3.1 s,
  0 errors in 30 in a row, transcription 26/30 (known gap, issue #38).
- Docs: `docs/archive/v1/`.

## v2 Teacher · tag v0.2.0 · current

- **Goal:** the assistant sees what I study, explains briefly at my level, remembers
  which concepts I asked about, and quizzes me when I ask.
- **At the end I can:**
  - hold Right Ctrl, ask "what is this graph?" and hear a short answer about my screen;
  - say "tell me more" or ask a follow-up, and it understands the context;
  - ask "what is LoRA?" and LoRA is logged as a concept I am learning;
  - say "quiz me": it asks about 2 to 3 concepts, grades each answer in one line, and
    does not ask those again unless I got them wrong;
  - ask "what did I learn this week?" and hear a short list.
- **Key pieces:**
  - Client keys: Right Alt = voice only (the v1 F9 job); Right Ctrl = voice plus a
    screenshot. Both keys are set in `client_pc/config.py`.
  - Sessions: the last few turns are kept for about 2 minutes, so follow-ups work.
  - Look: the screenshot is sent with the question to the same Gemini model.
  - Concept tracker in SQLite: short name, one-line summary, date asked, status, last
    quizzed. Only learning questions are logged; Gemini reuses an existing name when
    the concept is the same. No embeddings.
  - Quiz me, on request only: 2 to 3 concepts, never quizzed first, then ones answered
    wrong. Quizzed concepts are kept, never deleted.
  - Privacy: questions and screenshots go to the Gemini free tier. Never use Look on a
    private screen (bank, chats, passwords).
- **Out of scope:** long-term memory of me, embeddings, proactive quiz offers, habits,
  schedule, cloud deployment, open-source models, a spoken "look" word.
- **Done when:** targets set in the v2 spec (look answers, follow-ups, concept logging,
  quiz grading, latency).

## v3 Memory · tag v0.3.0

- **Goal:** it knows me and recalls our past conversations, stored as short key points.
- **At the end I can:** say "remember that ..." or "forget ..."; ask "what did we discuss
  about annotation last week?" or "what are my goals?"; list, delete and wipe memories.
- **Key pieces:**
  - Memory items are key points of at most about 12 words, never full transcripts, each
    with a type (fact about me, project, preference, session summary) and a date.
  - A memory writer runs after each session and keeps 0 to 3 key points.
  - Compaction merges near-duplicates and rolls old session summaries into monthly lines.
  - A profile of key facts is always in the prompt; other memories are searched on demand.
- **Open decision:** embeddings and the vector store (local model or API), at v3 start.
- **Done when:** targets set in the v3 spec, including a frozen recall test.

## v4 Planner and habits · tag v0.4.0

- **Goal:** it helps me run my day and build habits.
- **At the end I can:** add events to the assistant's own schedule and hear an alert before
  them; ask "what is my week?"; set recurring reminders ("drink water every 2 hours");
  say "let's track today's habits" and answer a short check-in ("Gym?" "Yes."); see my
  habit progress and insights on a small website.
- **Key pieces:** schedule table, recurring reminders, habit table, check-in conversation,
  a scheduler for alerts, a local dashboard page. Habit details (which habits, insights,
  rules from Atomic Habits) are brainstormed before v4 starts.
- **Done when:** targets set in the v4 spec.

## v5 Cloud · tag v0.5.0

- **Goal:** the laptop is only a client; the server runs in the cloud.
- **Key pieces:** server, database, scheduler and dashboard on an always-on host; managed
  Postgres; `AUTH_TOKEN` on every endpoint; HTTPS.
- **Done when:** the v2 to v4 evals pass against the cloud server, and reminders fire while
  the laptop server is off.

## v6 Own models · tag v0.6.0

- **Goal:** replace cloud APIs with open-source models wherever they are good enough.
- **Key pieces:** bake-offs for STT, LLM, vision, TTS and embeddings against the API
  baseline; a LoRA fine-tune of Whisper on my voice and AI words (issue #38); models
  served on serverless GPU behind an OpenAI-style API. A part switches only if its eval
  is at least as good.
- **Done when:** targets set in the v6 spec.

## v7 Wearable · tag v1.0.0

- **Goal:** the laptop client becomes a wearable device.
- **Key pieces:** a phone or glasses client with mic, speaker, button and camera; the camera
  frame replaces the screenshot; a spoken "look" word replaces the key.
- **Open decision:** the hardware, at v7 start. `hardware_plan.md` is an older reference.
- **Done when:** targets set in the v7 spec.

## Parked

Gym tracker (sets and reps), proactive quiz offers, Google Calendar sync, calls and SMS,
a phone app, the trend line in the habit tracker (until the v4 brainstorm).
