# AI Assistant (voice, v1)

A voice assistant that runs on a laptop. Hold the push-to-talk key (F9), ask a question or give
a command, let go, and hear the answer. It can search the web for live facts, keep notes, and
set, list and cancel reminders; due reminders are spoken aloud.

Pipeline: microphone -> faster-whisper -> Gemini with tools -> Piper -> speakers.

The long-term goal is a pair of glasses that act as a second brain; this is version 1.

## Requirements

- Windows, Python 3.11.
- An NVIDIA GPU with CUDA for speech recognition (developed on an RTX 3050 Laptop, 4 GB).
- A Gemini API key and a Tavily API key. Copy `.env.example` to `.env` and fill in both.
  `.env` is ignored by git and must never be committed.

## Setup

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m piper.download_voices en_US-lessac-medium --download-dir models
```

The speech recognition model downloads on the first run.

## Run

Start the server first, then the client:

```powershell
.venv\Scripts\python -m server.main
.venv\Scripts\python -m client_pc.client
```

Tests and checks:

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
```

Evaluation (30 questions, real Gemini, slow). Record the clips once, then run it with the
server up and the client stopped; it backs up your notes and reminders and restores them after:

```powershell
.venv\Scripts\python -m eval.record
.venv\Scripts\python -m eval.run_eval
.venv\Scripts\python -m eval.live_log
```

## Measured results

From the final run of the 30-question evaluation (`eval/results/2026-10-11_1555.md`):

| Check | Result | Target |
| --- | --- | --- |
| General and live questions | 8/10 | 80% |
| Notes | 10/10 | 80% |
| Reminders | 10/10 | 80% |
| Transcription | 87% (26/30) | 90%, missed by one clip |
| Median time, key release to answer | 3.1 s | 15 s |
| Errors | 0 | none |

Questions that search the web take about 6 s. The transcription target is missed and accepted
as a known gap; see `docs/plan.md`.

## Known limits

- Rare names are sometimes misheard (for example "ISRO" heard as "Israel").
- Speech recognition is English only.
- In a rare worst case (about 20 s) the assistant may say it could not look something up,
  or return an error.
- The Gemini free tier limits requests per minute and per day.

## Privacy

Audio stays on the laptop: it is transcribed locally and never uploaded. The question text and
tool results are sent to Gemini, and the search query alone is sent to Tavily. Notes and
reminders are stored in a local SQLite database that is not committed.

## Roadmap

- v2: phone link (the phone becomes the client; calls, texts and calendar after a spoken yes).
- v3: Remember (private memory of what I said and discussed, with a local text model).
- v4: audio wearable (glasses replace the phone as the push-to-talk client).
- v5: camera (ask about what is in front of me).

Details are in `docs/roadmap.md`.
