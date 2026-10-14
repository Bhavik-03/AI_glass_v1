Version 2. See roadmap.md.

# AI Assistant v2 Brief: Teacher

Updated Oct 14, 2026 · Bhavik Fulfagar · tag v0.2.0

## 1. One-liner

A study companion on my laptop: hold a key, ask by voice, optionally about what is on my
screen, and hear a short spoken answer. It logs the concepts I ask about and quizzes me
when I ask.

## 2. Problem

While self-studying (for example, a self-annotation project) I keep meeting terms I don't
know. Each time I switch to my phone or browser and lose focus. I forget what I looked up,
and nothing checks that I understood it.

## 3. User

Me, an engineering student studying at my laptop. I want to hold a key and ask "what is
this graph?", say "tell me more", ask "what is LoRA?", say "quiz me" or ask "what did I
learn this week?", and hear the answer without leaving what I am reading.

## 4. v2 scope (in)

v2 runs on the laptop only, like v1. Answers are 1 to 3 short sentences, by voice only;
nothing is shown on screen.

- **Right Alt:** ask by voice, as in v1 (questions, notes, reminders). It replaces F9.
- **Right Ctrl ("Look"):** ask by voice about what is on my screen; a screenshot is sent
  with the question.
- **Follow-ups:** follow-up questions and "tell me more" work for about 2 minutes after a
  question.
- **Concepts:** learning questions are logged as concepts.
- **Quiz me:** asks about 2 to 3 logged concepts, grades each answer in one line, and does
  not ask them again unless I got them wrong.
- **What did I learn this week?:** a short spoken list.
- **Logging:** issue #59, the log records whether a tool was refused or failed.

## 5. Out of scope

- Long-term memory, embeddings
- Proactive quiz offers
- Habits, schedule
- Cloud
- Open-source models
- A spoken "look" word

## 6. Privacy

- Questions and screenshots go to the Gemini free tier.
- Screenshots are not saved to disk; the log only records that an image was sent.
- The eval keeps its own saved screenshots.
- Never use Look on a private screen (bank, chats, passwords).

## 7. Success criteria and constraints

Proposed targets; the final ones are in spec.md.

| Metric | Target |
| --- | --- |
| Look | ≥ 80% correct on 20 saved screenshots |
| Follow-ups | ≥ 8 of 10 |
| Concept logging | Logged or skipped correctly in ≥ 90% of 20 questions |
| Quiz grading | Agrees with me in ≥ 8 of 10 |
| Latency with an image | ≤ 8 s median |
| v1 regression | A re-run of the v1 eval still meets every v1 target |

Constraints:

- Gemini free tier: 15 requests per minute, 500 per day.
- Compute: RTX 3050 Laptop GPU (4 GB VRAM).
- Laptop only; no screen output.
- No new dependency without my approval.

## 8. Deliverables

- Tag v0.2.0 on main with the v2 evaluation results.
- A new frozen v2 eval set and its final report in eval/results/.
- README updated for v2 (keys, Look, quiz me).
