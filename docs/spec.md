# AI Assistant Glasses — v1 Spec

Updated Oct 5, 2026 · Bhavik Fulfagar

v1 answers one spoken question, about a photo or on its own, with a spoken answer within 15 s, using two buttons: Look (photo + question) and Ask (question only). Speech-to-text and text-to-speech run locally on the laptop; Gemini Flash or Flash-Lite answers through the API. No fixed deadline: Phase A first, then Phase B. Scope and out-of-scope items are in the v1 Brief.

## How it works

Two clients talk to one laptop server through the same API, so the server never changes when the glasses replace the webcam.

- **Phase A:** a Python client on the laptop uses the webcam, the built-in mic and two keyboard keys as the Look and Ask buttons.
- **Phase B:** the ESP32-S3 glasses replace the Python client, powered over USB-C from a power bank in v1. Glasses and laptop join the same phone hotspot, with mobile data on for the Gemini API.

User flow, push-to-talk. Each button is one press-and-hold: press to start, speak while holding, release to send. Look takes its photo at the moment of the press, before you speak.

1. User presses and holds Look or Ask. Look takes one photo at that instant and plays a camera-shutter sound; Ask takes no photo and plays a two-note chime.
2. While the button is held, the client records the spoken question.
3. User releases the button. The client sends the audio, plus the photo for Look, to the server and plays a "thinking" tone.
4. The server transcribes the question, asks Gemini (which searches the web itself when a question needs live information), and converts the answer to speech.
5. The server returns the complete answer audio file.
6. The client plays the answer through the speaker.

## Functional requirements

Eleven requirements cover the loop. Each ID later becomes one build task and one test.

| ID | Requirement | Input → Output | Acceptance criteria |
| --- | --- | --- | --- |
| FR-1 | Capture one photo the moment the Look button is pressed | Button press → JPEG, 640×480 (VGA) | 20 of 20 presses give a sharp, well-exposed photo |
| FR-2 | Record the question while either button is held, 10 s max | Button hold → WAV, 16 kHz mono 16-bit | Speech clear on playback in 20 of 20 tests; stops at release or 10 s |
| FR-3 | Send the audio and the photo in one request; the photo is optional | WAV + optional JPEG → HTTP POST /query | Reaches the server in ≤ 1 s over the hotspot |
| FR-4 | Transcribe the question locally with faster-whisper small.en | WAV → question text | ≥ 90% of test questions keep their meaning; ≤ 1 s each |
| FR-5 | Answer with Gemini Flash or Flash-Lite through the API: thinking off or minimal, 8 s call timeout, answers ≤ 2 short sentences (under 40 words), API key read from an environment variable, Google Search grounding enabled on every request; the system instruction tells Gemini to use the photo only when the question is about what the user sees | Question text, plus JPEG when sent → answer text | ≥ 80% correct on the visual set and on the audio-only set; ≤ 8 s each |
| FR-6 | Convert the answer to speech with Piper | Answer text → WAV, resampled to 16 kHz mono | ≤ 1 s for a 40-word answer; every word understandable |
| FR-7 | Return the complete answer audio and play it | WAV → sound from the speaker | Download plus playback start ≤ 1 s; audible in a quiet lab |
| FR-8 | Play status tones: camera-shutter sound on a Look press, two-note chime on an Ask press, thinking tone after release, error tone on failure | Client events → tones | The user can tell the system's state without a screen |
| FR-9 | Handle errors: 20 s client timeout, server rejects bad input instead of crashing, client reconnects to Wi-Fi | Failure → error tone, server keeps running | Server survives empty audio and a corrupt image; client recovers after a Wi-Fi drop |
| FR-10 | Log every query on the server | Each query → one JSONL line (question, answer, per-stage timings, whether a photo was sent, whether Gemini searched) + saved photo if any | Every test query has a complete log line; timings feed the README |
| FR-11 | Answer Ask-button questions: a request with no photo is answered from the question text, with Google Search for live information such as weather or news | WAV, no JPEG → answer WAV | ≥ 80% of the 10 audio-only test questions correct |

## Interface contract

Both clients use exactly this API. Freeze it before writing code; changing it later means changing the firmware too.

```text
POST /query                         # one question, one answer
  Content-Type: multipart/form-data
  audio  : WAV file, 16 kHz mono    # the question (FR-2), required
  image  : JPEG file, optional      # the photo (FR-1); omitted = audio-only (FR-11)

  200 OK                            # success
    Content-Type: audio/wav         # complete answer audio (FR-6)
  400 Bad Request                   # audio missing, or a file unreadable
    {"error": "<reason>"}
  500 Internal Server Error         # a stage failed
    {"error": "<stage>: <reason>"}

GET /health                         # is the server up and the model loaded?
  200 OK  {"status": "ok", "model": "<vlm name>"}
```

The server listens on a fixed port on the hotspot network. The client stores the laptop's IP and port in one config value.

## Quality targets

v1 is done when every target below is met; power and comfort apply to Phase B only.

| Metric | Target | How measured |
| --- | --- | --- |
| End-to-end latency (button release → first answer audio) | ≤ 15 s, median over all 30 test questions | Client timer + server stage timings (FR-10) |
| Answer correctness | ≥ 80% of the 20 visual questions and ≥ 80% of the 10 audio-only questions | Test plan below |
| Transcription | ≥ 90% of questions keep their meaning | Compare logged question text with the written question |
| Reliability | 20 queries in a row, no crash or manual reconnect | One continuous run |
| API key safety | Key never in code or on GitHub | Key read from an environment variable; .env listed in .gitignore |
| Power (Phase B) | Runs 1 h on a USB power bank at about 1 query per minute | One continuous session; the power bank must not switch itself off |
| Comfort (Phase B) | Worn 30 min without taking it off | Wear it during a lab session |

The 15 s budget per stage: upload 1 s + STT 1 s + VLM 8 s + TTS 1 s + download and play 1 s = 12 s, leaving 3 s of margin. If a run is slow, the logs show which stage broke its budget and whether Gemini searched.

## Test plan

Two fixed sets are written and frozen before the first test run, then run once in Phase A and once in Phase B: 20 visual questions sent with a photo, and 10 audio-only questions sent without one.

| Set | Category | Questions | Example |
| --- | --- | --- | --- |
| Visual | Everyday objects | 10 | A phone, book or fan held up: "What is this?" |
| Visual | Finger counting | 10 | One to five fingers on either hand: "How many fingers am I holding up?" |
| Audio-only | General and live questions | 10 | "What is the capital of Japan?" or "What's the weather today?" |

1. Write all 30 rows in `tests/questions.csv` with columns id, category, setup, question, expected_answer. Setup says what is in front of the camera, or "none" for audio-only. Do this before running anything.
2. Send audio-only questions without a photo, so they test FR-11.
3. Grade each answer as correct, partial or wrong. Only "correct" counts toward the 80% targets.
4. Report accuracy per set and per category, plus median and worst latency.
5. Re-run both sets whenever the VLM, prompt or image resolution changes, so results stay comparable.

Live questions such as today's weather or the news are answered through Google Search. Their expected answer is checked against a trusted website at the time of the test, and the home city for weather questions comes from the server config.

## Decisions settled in Design

- [x] VLM: Gemini Flash or Flash-Lite through the API
- [x] Speech-to-text: faster-whisper small.en, running locally
- [x] Image: 640×480 JPEG, optional per request
- [x] Server: FastAPI, with STT and TTS loaded once in a single process (details in design.md)
- [x] Firmware: Arduino framework built with arduino-cli; pin map in expense_v1.md
- [x] Parts: about ₹2,345–3,480 within the ₹4,000 budget; list in expense_v1.md
- [x] Mounting: all parts on the right arm, USB power bank in v1; layout in expense_v1.md
