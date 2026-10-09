# Roadmap

Updated Oct 9, 2026 · Bhavik Fulfagar

## Final goal

Glasses that act as my second brain and handle most quick phone tasks hands-free: answer questions (with live info), take notes, set reminders, manage my calendar, call and text my contacts, privately remember what I said and discussed, and later see what I see.

- Single user (me), no accounts.
- Phone: Android. Messages: SMS only. Calendar: Google Calendar.
- Hero feature: memory, stored on my own machine. Gemini sees only what is sent to it.
- Phone tasks are the useful base the memory builds on.

## Process rule

- Only the current version has detailed docs: `brief.md`, `spec.md`, `design.md` (and `plan.md`) in `docs/`.
- At the end of a version: copy them to `docs/archive/vN/`, tag the release, then write the next version's docs.
- Milestone IDs continue across versions (v1 ends at M7, so v2 starts at M8).

## v1 Voice assistant · tag v0.1.0 · current

- **Goal:** a spoken assistant on the laptop that answers questions and keeps my notes and reminders.
- **At the end I can:** hold one key, ask a general or live question, add or list notes, set, list or cancel reminders, and hear due reminders spoken on time.
- **Key pieces:**
  - Push-to-talk PC client: one key, start, thinking and error sounds; polls for due reminders.
  - Server: faster-whisper `small.en` → Gemini Flash with Google Search and function calling → Piper TTS.
  - Tools: `add_note`, `list_notes`, `add_reminder`, `list_reminders`, `cancel_reminder`, stored in SQLite.
  - Current date and time (Asia/Kolkata) in the system prompt; every action is repeated back.
  - Server binds to 127.0.0.1.
- **Milestones:** M1 server skeleton, config and logger · M2 speech-to-text · M3 Gemini answers with Search · M4 TTS and full /query pipeline with server errors · M5 tools: notes and reminders · M6 PC client · M7 evaluation and reliability.
- **Out of scope:** camera, phone, calendar, calls, SMS, memory, network access from other devices, wake word, streaming audio.
- **Done when:** 30 spoken questions (10 general and live, 10 notes, 10 reminders) reach ≥ 80% correct per group, median latency ≤ 15 s, and 20 queries in a row run without a crash.

## v2 Phone link · tag v0.2.0

- **Goal:** the phone becomes the client and the hands for phone tasks.
- **At the end I can:** talk through my phone, call and text contacts by name after a spoken "yes", and read and add Google Calendar events.
- **Key pieces:**
  - Android companion app: push-to-talk client (phone mic and speaker) plus an action bridge for calls, SMS and contact lookup by name.
  - Due reminders shown as text on the phone and played as audio, using the v1 reminder endpoints unchanged.
  - Google Calendar read and add through the API (OAuth; token file gitignored).
  - Calls and SMS always need a spoken "yes": the server holds a pending action until confirmed or cancelled.
  - Server listens on the hotspot; an `AUTH_TOKEN` header on every endpoint, so nobody else on the network can make my phone call or text.
- **Out of scope:** memory, glasses hardware, camera, messaging apps other than SMS.
- **Open decision:** app framework (Kotlin or Flutter), decided at v2 start.
- **Done when:** targets set in the v2 spec.

## v3 Remember · tag v0.3.0

- **Goal:** the assistant remembers what I said and discussed, privately.
- **At the end I can:** ask about past questions, answers and notes; record a conversation or lecture and get a summary and follow-ups; list, delete and wipe memories.
- **Key pieces:**
  - Voice memory of questions, answers and notes; a personal profile file.
  - Consent-aware conversation and lecture recording with an audible start signal, then a summary and follow-ups.
  - `SEND_MEMORY_TO_GEMINI=false` by default: memory questions go to a small local text model that fits 4 GB VRAM, chosen by a bake-off of current models.
- **Out of scope:** photo memory, glasses hardware, camera.
- **Done when:** targets set in the v3 spec.

## v4 Wearable (audio only) · tag v0.4.0

- **Goal:** the glasses replace the phone as the push-to-talk client.
- **At the end I can:** wear glasses with a mic, speaker, button and battery and use everything from v1–v3.
- **Key pieces:** glasses with mic, speaker, button and battery.
- **Open decision:** the board, chosen at v4 start. Call audio through the glasses needs a Bluetooth headset profile, which the ESP32-S3 does not support (BLE only).
- **Out of scope:** camera.
- **Done when:** targets set in the v4 spec.

## v5 Camera · tag v1.0.0

- **Goal:** the glasses see what I see.
- **At the end I can:** press Look and ask about what is in front of me; photos become part of memory.
- **Key pieces:** Look button, vision questions, local VLM router, photo memory. The hardware plan (`hardware_plan.md`, XIAO ESP32S3 Sense) applies here.
- **Done when:** targets set in the v5 spec.
