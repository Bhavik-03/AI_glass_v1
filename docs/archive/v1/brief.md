Version 1. See roadmap.md.

# AI Assistant v1 Brief: Voice assistant

Updated Oct 9, 2026 · Bhavik Fulfagar

## 1. One-liner

A push-to-talk voice assistant on my laptop: hold one key, ask a question or give a command, and hear a short spoken answer. It answers with live information, keeps my notes and sets reminders that it speaks when they are due.

## 2. Problem

Quick tasks break focus. Looking something up, writing a note or setting a reminder means picking up the phone, unlocking it, opening an app and typing, often with both hands busy at the lab bench.

Commercial assistants are closed: I can't change the model, the prompts or where my data is stored. v1 builds the open base the later versions grow from (roadmap.md).

## 3. User

Me, the builder: a robotics and AI engineering student working at a laptop or lab bench. I want to ask "what's the weather today?", say "note: the motor driver needs 12 V", "remind me tomorrow at 5 to call the lab", or "what are my reminders?", and hear the answer without typing.

## 4. Why us

The edge is control, not polish: an open pipeline where every part can be swapped and studied.

| Existing option | Gap | What v1 does |
| --- | --- | --- |
| Phone assistants | Closed model and prompts; data in the vendor's cloud | Own prompts and models; notes and reminders in a local SQLite file |
| Notes and reminder apps | Need hands and several taps | One key, one spoken sentence |
| Chat apps with search | Typing, reading, no reminders | Voice in, voice out, live answers and reminders |

## 5. v1 scope (in)

v1 runs on the laptop only. One FastAPI server and one Python client, both on the same machine.

- **Client:** one push-to-talk key, start, thinking and error sounds, plays the answer. Polls the server every 10 s for due reminders and plays them.
- **Speech to text:** faster-whisper `small.en`, local.
- **Answers:** Gemini (`gemini-3.5-flash-lite`) with function calling; live information through a `web_search` tool that the server runs against a web search API.
- **Tools:** `add_note`, `list_notes`, `add_reminder`, `list_reminders`, `cancel_reminder`, stored in a local SQLite database.
- **Time:** the system prompt includes the current date and time in Asia/Kolkata, so "tomorrow at 5" becomes an exact time.
- **Confirmation:** every action is repeated back ("Reminder set for 5 pm tomorrow: call the lab").
- **Due reminders:** spoken when due; a reminder missed while the client was off is spoken at the next poll as a missed reminder.
- **Text to speech:** Piper, local.
- **Network:** the server binds to 127.0.0.1; only the laptop can reach it.

The loop:

1. Hold the key; the start sound plays. Speak.
2. Release; the thinking sound plays and the question audio goes to the server.
3. The server transcribes it, asks Gemini (which may search the web or call a tool), runs any tool calls, and turns the answer into speech.
4. The client plays the answer.

Single question, single answer, English only.

## 6. Out of scope

- Camera, photos, Look button, any vision (v5)
- Glasses or any other hardware (v4)
- Phone app, calls, SMS, contacts, Google Calendar (v2)
- Reminders as phone notifications (v2)
- Memory of past questions and answers, recording, local text model (v3)
- Access from other devices on the network, auth tokens (v2)
- Wake word, streaming audio, multi-turn conversation
- Editing notes or reminders, repeating reminders
- Languages other than English

## 7. Success criteria and constraints

Measured on 30 spoken questions: 10 general and live, 10 notes commands, 10 reminder commands.

| Metric | Target |
| --- | --- |
| Correctness | ≥ 80% per group; a tool question passes when the right tool is called with the right arguments and the result is stored |
| Latency (key release to first answer audio) | ≤ 15 s median |
| Transcription | ≥ 90% of questions keep their meaning |
| Reliability | 20 queries in a row without a crash |
| Due reminders | Spoken within one poll interval (10 s) of the due time while the client runs; never lost when the client is closed |
| Secrets | API key, `.env` and the database never in git; keys never logged |

Exact thresholds and the test plan are in spec.md.

Constraints:

- Team: one person.
- Compute: HP Omen laptop, RTX 3050 Laptop GPU (4 GB VRAM); Gemini API for answers.
- Network: internet for the Gemini API; everything else local.
- Timeline: no fixed deadline.

## 8. Deliverables

- GitHub repo with README: what it does, architecture diagram, setup steps
- Tag v0.1.0 with the evaluation results
- 1–2 min demo video: a live question, a note, and a reminder that is spoken when due
