# M17-T10 runs: live-run record of the writer guard

Real Gemini through the real poll flow, 15 writer calls, 5 s apart, no retries. Per run: raw writer reply, writer log line, stored rows and the poll response.

## 1_f run 1 (2.6 s, poll 204)

- finish: ['FinishReason.STOP']
- raw writer reply: `'{\n  "points": [\n    {\n      "text": "Working on a fingerprint-sensor project",\n      "type": "project"\n    }\n  ]\n}'`
- writer log line: `{"time": "2026-10-26T16:51:41+05:30", "event": "session_writer", "turns": 2, "points_returned": 1, "rows_added": 0, "points_too_long": 0, "points_rejected": 1, "dropped": [{"direction": "ungrounded", "grounded": 0.0, "known": 0.25, "leak": 1, "text": "Working on a fingerprint-sensor project"}], "timings_ms": {"llm": 2536}, "error": null}`
- rows before the poll: []
- stored rows after the poll: []
- poll response: null

## 1_f run 2 (2.3 s, poll 204)

- finish: ['FinishReason.STOP']
- raw writer reply: `'{\n  "points": [\n    {\n      "text": "Working on a fingerprint-sensor project",\n      "type": "project"\n    }\n  ]\n}'`
- writer log line: `{"time": "2026-10-26T16:51:48+05:30", "event": "session_writer", "turns": 2, "points_returned": 1, "rows_added": 0, "points_too_long": 0, "points_rejected": 1, "dropped": [{"direction": "ungrounded", "grounded": 0.0, "known": 0.25, "leak": 1, "text": "Working on a fingerprint-sensor project"}], "timings_ms": {"llm": 2242}, "error": null}`
- rows before the poll: []
- stored rows after the poll: []
- poll response: null

## 1_f run 3 (1.3 s, poll 204)

- finish: ['FinishReason.STOP']
- raw writer reply: `'{\n  "points": [\n    {\n      "text": "Working on a fingerprint-sensor project",\n      "type": "project"\n    }\n  ]\n}'`
- writer log line: `{"time": "2026-10-26T16:51:55+05:30", "event": "session_writer", "turns": 2, "points_returned": 1, "rows_added": 0, "points_too_long": 0, "points_rejected": 1, "dropped": [{"direction": "ungrounded", "grounded": 0.0, "known": 0.25, "leak": 1, "text": "Working on a fingerprint-sensor project"}], "timings_ms": {"llm": 1261}, "error": null}`
- rows before the poll: []
- stored rows after the poll: []
- poll response: null

## 2_f2 run 1 (2.3 s, poll 204)

- finish: ['FinishReason.STOP']
- raw writer reply: `'{\n  "points": [\n    {\n      "text": "Maintaining a Rust compiler fork",\n      "type": "project"\n    }\n  ]\n}'`
- writer log line: `{"time": "2026-10-26T16:52:02+05:30", "event": "session_writer", "turns": 2, "points_returned": 1, "rows_added": 0, "points_too_long": 0, "points_rejected": 1, "dropped": [{"direction": "ungrounded", "grounded": 0.0, "known": 0.0, "leak": 0, "text": "Maintaining a Rust compiler fork"}], "timings_ms": {"llm": 2290}, "error": null}`
- rows before the poll: []
- stored rows after the poll: []
- poll response: null

## 2_f2 run 2 (1.7 s, poll 204)

- finish: ['FinishReason.STOP']
- raw writer reply: `'{\n  "points": [\n    {\n      "text": "Maintaining a Rust compiler fork",\n      "type": "project"\n    }\n  ]\n}'`
- writer log line: `{"time": "2026-10-26T16:52:09+05:30", "event": "session_writer", "turns": 2, "points_returned": 1, "rows_added": 0, "points_too_long": 0, "points_rejected": 1, "dropped": [{"direction": "ungrounded", "grounded": 0.0, "known": 0.0, "leak": 0, "text": "Maintaining a Rust compiler fork"}], "timings_ms": {"llm": 1730}, "error": null}`
- rows before the poll: []
- stored rows after the poll: []
- poll response: null

## 2_f2 run 3 (0.9 s, poll 204)

- finish: ['FinishReason.STOP']
- raw writer reply: `'{\n  "points": [\n    {\n      "text": "Maintaining a Rust compiler fork",\n      "type": "project"\n    }\n  ]\n}'`
- writer log line: `{"time": "2026-10-26T16:52:14+05:30", "event": "session_writer", "turns": 2, "points_returned": 1, "rows_added": 0, "points_too_long": 0, "points_rejected": 1, "dropped": [{"direction": "ungrounded", "grounded": 0.0, "known": 0.0, "leak": 0, "text": "Maintaining a Rust compiler fork"}], "timings_ms": {"llm": 885}, "error": null}`
- rows before the poll: []
- stored rows after the poll: []
- poll response: null

## 3_leak_a run 1 (0.9 s, poll 200)

- finish: ['FinishReason.STOP']
- raw writer reply: `'{\n  "points": [\n    {\n      "text": "Building a climate logger sensor board as main semester project",\n      "type": "project"\n    }\n  ]\n}'`
- writer log line: `{"time": "2026-10-26T16:52:20+05:30", "event": "session_writer", "turns": 2, "points_returned": 1, "rows_added": 1, "points_too_long": 0, "points_rejected": 0, "dropped": [], "timings_ms": {"llm": 873}, "error": null}`
- rows before the poll: []
- stored rows after the poll: [{"text": "Building a climate logger sensor board as main semester project", "type": "project"}]
- poll response: [{"id": 1, "text": "Noted one thing.", "due_at": "2026-10-26T16:02:11+05:30"}]

## 3_leak_a run 2 (1.6 s, poll 200)

- finish: ['FinishReason.STOP']
- raw writer reply: `'{\n  "points": [\n    {\n      "text": "Building a climate logger sensor board as main project",\n      "type": "project"\n    }\n  ]\n}'`
- writer log line: `{"time": "2026-10-26T16:52:27+05:30", "event": "session_writer", "turns": 2, "points_returned": 1, "rows_added": 1, "points_too_long": 0, "points_rejected": 0, "dropped": [], "timings_ms": {"llm": 1599}, "error": null}`
- rows before the poll: []
- stored rows after the poll: [{"text": "Building a climate logger sensor board as main project", "type": "project"}]
- poll response: [{"id": 1, "text": "Noted one thing.", "due_at": "2026-10-26T16:02:11+05:30"}]

## 3_leak_a run 3 (2.3 s, poll 200)

- finish: ['FinishReason.STOP']
- raw writer reply: `'{\n  "points": [\n    {\n      "text": "Building a climate logger sensor board as main project",\n      "type": "project"\n    }\n  ]\n}'`
- writer log line: `{"time": "2026-10-26T16:52:34+05:30", "event": "session_writer", "turns": 2, "points_returned": 1, "rows_added": 1, "points_too_long": 0, "points_rejected": 0, "dropped": [], "timings_ms": {"llm": 2260}, "error": null}`
- rows before the poll: []
- stored rows after the poll: [{"text": "Building a climate logger sensor board as main project", "type": "project"}]
- poll response: [{"id": 1, "text": "Noted one thing.", "due_at": "2026-10-26T16:02:11+05:30"}]

## 4_d run 1 (1.5 s, poll 204)

- finish: ['FinishReason.STOP']
- raw writer reply: `'{\n  "points": [\n    {\n      "text": "Soldering lab closes at five on Fridays",\n      "type": "fact"\n    }\n  ]\n}'`
- writer log line: `{"time": "2026-10-26T16:52:41+05:30", "event": "session_writer", "turns": 2, "points_returned": 1, "rows_added": 0, "points_too_long": 0, "points_rejected": 0, "dropped": [], "timings_ms": {"llm": 1531}, "error": null}`
- rows before the poll: [{"text": "Soldering lab closes at five on Fridays", "type": "fact"}]
- stored rows after the poll: [{"text": "Soldering lab closes at five on Fridays", "type": "fact"}]
- poll response: null

## 4_d run 2 (1.7 s, poll 204)

- finish: ['FinishReason.STOP']
- raw writer reply: `'{\n  "points": [\n    {\n      "text": "Soldering lab closes at five on Fridays",\n      "type": "fact"\n    }\n  ]\n}'`
- writer log line: `{"time": "2026-10-26T16:52:48+05:30", "event": "session_writer", "turns": 2, "points_returned": 1, "rows_added": 0, "points_too_long": 0, "points_rejected": 0, "dropped": [], "timings_ms": {"llm": 1678}, "error": null}`
- rows before the poll: [{"text": "Soldering lab closes at five on Fridays", "type": "fact"}]
- stored rows after the poll: [{"text": "Soldering lab closes at five on Fridays", "type": "fact"}]
- poll response: null

## 4_d run 3 (1.8 s, poll 204)

- finish: ['FinishReason.STOP']
- raw writer reply: `'{\n  "points": [\n    {\n      "text": "Soldering lab closes at five on Fridays",\n      "type": "fact"\n    }\n  ]\n}'`
- writer log line: `{"time": "2026-10-26T16:52:54+05:30", "event": "session_writer", "turns": 2, "points_returned": 1, "rows_added": 0, "points_too_long": 0, "points_rejected": 0, "dropped": [], "timings_ms": {"llm": 1774}, "error": null}`
- rows before the poll: [{"text": "Soldering lab closes at five on Fridays", "type": "fact"}]
- stored rows after the poll: [{"text": "Soldering lab closes at five on Fridays", "type": "fact"}]
- poll response: null

## 5_i2 run 1 (2.9 s, poll 200)

- finish: ['FinishReason.STOP']
- raw writer reply: `'{\n  "points": [\n    {\n      "text": "Campus event ticketing app uses UPI deep links for payments",\n      "type": "project"\n    },\n    {\n      "text": "Campus event ticketing app sends notifications via WhatsApp Business messages",\n      "type": "project"\n    }\n  ]\n}'`
- writer log line: `{"time": "2026-10-26T16:53:02+05:30", "event": "session_writer", "turns": 3, "points_returned": 2, "rows_added": 2, "points_too_long": 0, "points_rejected": 0, "dropped": [], "timings_ms": {"llm": 2916}, "error": null}`
- rows before the poll: []
- stored rows after the poll: [{"text": "Campus event ticketing app uses UPI deep links for payments", "type": "project"}, {"text": "Campus event ticketing app sends notifications via WhatsApp Business messages", "type": "project"}]
- poll response: [{"id": 1, "text": "Noted two things.", "due_at": "2026-10-26T16:02:21+05:30"}]

## 5_i2 run 2 (3.7 s, poll 200)

- finish: ['FinishReason.STOP']
- raw writer reply: `'{\n  "points": [\n    {\n      "text": "Campus event ticketing app uses UPI deep links for payments module",\n      "type": "project"\n    },\n    {\n      "text": "Campus event ticketing app sends notifications via WhatsApp Business messages",\n      "type": "project"\n    }\n  ]\n}'`
- writer log line: `{"time": "2026-10-26T16:53:11+05:30", "event": "session_writer", "turns": 3, "points_returned": 2, "rows_added": 2, "points_too_long": 0, "points_rejected": 0, "dropped": [], "timings_ms": {"llm": 3654}, "error": null}`
- rows before the poll: []
- stored rows after the poll: [{"text": "Campus event ticketing app uses UPI deep links for payments module", "type": "project"}, {"text": "Campus event ticketing app sends notifications via WhatsApp Business messages", "type": "project"}]
- poll response: [{"id": 1, "text": "Noted two things.", "due_at": "2026-10-26T16:02:21+05:30"}]

## 5_i2 run 3 (1.8 s, poll 200)

- finish: ['FinishReason.STOP']
- raw writer reply: `'{\n  "points": [\n    {\n      "text": "Campus event ticketing app payments module uses UPI deep links",\n      "type": "project"\n    },\n    {\n      "text": "Campus event ticketing app notifications use WhatsApp Business messages",\n      "type": "project"\n    }\n  ]\n}'`
- writer log line: `{"time": "2026-10-26T16:53:18+05:30", "event": "session_writer", "turns": 3, "points_returned": 2, "rows_added": 2, "points_too_long": 0, "points_rejected": 0, "dropped": [], "timings_ms": {"llm": 1824}, "error": null}`
- rows before the poll: []
- stored rows after the poll: [{"text": "Campus event ticketing app payments module uses UPI deep links", "type": "project"}, {"text": "Campus event ticketing app notifications use WhatsApp Business messages", "type": "project"}]
- poll response: [{"id": 1, "text": "Noted two things.", "due_at": "2026-10-26T16:02:21+05:30"}]
