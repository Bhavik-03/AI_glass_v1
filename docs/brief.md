# AI Assistant Glasses — v1 Brief

Updated Oct 5, 2026 · Bhavik Fulfagar

## 1. One-liner

DIY glasses that let you ask a question out loud, about whatever you're looking at or anything else, and hear a spoken answer in a few seconds, hands-free.

## 2. Problem

Getting AI help about something in front of you takes about five steps and both hands. You stop, pull out your phone, open an app, point the camera, type or speak, then read the answer.

That breaks whatever you were doing: walking, cooking, or working at a bench with tools in hand. Commercial AI glasses solve the hands-free part, but they are closed: you can't change the model, the prompts, or add your own features.

## 3. User

The builder himself: a robotics and AI engineering student working at a lab bench with both hands busy. He wants to ask things like "what is this?", "how many fingers am I holding up?" or "what component is this?", a quick general question, or a live one like today's weather, without putting down tools or picking up a phone.

Designing for one real daily user keeps v1 honest; wider audiences (visually impaired users, field technicians) come after v1 works.

## 4. Why us

The edge is control, not polish: an open pipeline where every part can be swapped and studied.

| Existing option | Gap | What this project does |
| --- | --- | --- |
| Phone apps (camera + AI chat, visual search) | Need hands and 5+ steps | One button press, answer in your ear |
| Commercial AI glasses | Closed model, prompts and data | Swap any VLM (API or open-source), own prompts, option to keep data local later |
| Object detectors like YOLO | Fixed labels, can't answer questions | Vision-language model answers open-ended questions |

It is also a low-cost build from off-the-shelf parts, so it doubles as a learning platform for CV, LLMs and embedded systems.

## 5. v1 scope (in)

v1 proves one loop works end to end: camera + voice in, spoken answer out. It is built in two phases that share one server:

- **Phase A:** a Python client on the laptop (webcam, built-in mic, two keyboard keys as the Look and Ask buttons).
- **Phase B:** the glasses replace the Python client.

Hardware (Phase B):

- Seeed XIAO ESP32S3 Sense (camera and mic on board)
- MAX98357A I2S amplifier and a small 8 Ω, 1 W speaker
- Two push buttons: Look (photo + question) and Ask (question only), each with its own sound
- Powered over USB-C from a power bank
- Mounted on the right arm of a pair of safety glasses

The loop:

1. Press and hold **Look** or **Ask**. Look takes one photo (640×480 JPEG) the moment it is pressed and plays a camera-shutter sound; Ask takes no photo and plays a two-note chime.
2. Speak the question while holding the button.
3. Release: the audio, plus the photo for Look, goes over Wi-Fi to the laptop server.
4. STT (faster-whisper `small.en`, running locally) turns the question into text.
5. Gemini Flash or Flash-Lite answers through the API. Google Search is enabled, so live questions such as today's weather work too.
6. TTS (Piper, running locally) turns the answer into speech, and the complete audio file plays on the glasses speaker.

Single question, single answer, English only.

## 6. Out of scope

- Display or any visual output
- Extra sensors (IMU, touch, proximity)
- YOLO or any always-on, real-time detection
- Wake word (the buttons replace it in v1)
- Running models on the glasses themselves
- A local VLM (planned for a later version; v1 uses the Gemini API)
- Streaming audio (v1 sends the complete answer file)
- Battery power (v1 runs on USB; LiPo comes later)
- Bone-conduction audio
- Phone app (the laptop acts as the server)
- Multi-turn conversation or memory of past questions
- Video input, more than one photo per question
- Languages other than English
- Custom PCB, slim form factor, battery optimisation

## 7. Success criteria and constraints

v1 works if it hits every target below on two fixed test sets: 20 visual questions (10 everyday objects, 10 finger counts) and 10 Ask-button questions, including live ones such as today's weather.

| Metric | Target |
| --- | --- |
| End-to-end latency (button release to first audio) | ≤ 15 s (median) |
| Answer correctness (judged by the user) | ≥ 80% of the visual set and of the audio-only set |
| Question transcribed correctly by STT | ≥ 90% |
| Reliability | 20 queries in a row with no crash or reconnect |
| Power (Phase B) | Runs 1 hour on a USB power bank at about 1 query per minute |
| Comfort (Phase B) | Worn for 30 min without needing to take it off |

Constraints:

- Team: one person (the builder).
- Compute: HP Omen laptop, RTX 4050 (6 GB VRAM), as the server; Gemini API for the VLM.
- Network: glasses and laptop on the same Wi-Fi or phone hotspot, with internet for the Gemini API.
- Hardware: off-the-shelf parts only, no custom PCB.
- Budget: about ₹4,000 for hardware.
- Timeline: no fixed deadline. Phase A first, then Phase B.

## 8. Deliverables

- GitHub repo with README: what it does, architecture diagram, setup steps
- 1–2 min demo video of real questions at the lab bench
