Version 3. See roadmap.md.

# AI Assistant v3 Brief: Memory

Updated Oct 20, 2026 · Bhavik Fulfagar · tag v0.3.0

## 1. One-liner

An assistant that knows me: it keeps short key points about me, my projects and
our past conversations, and uses them so I do not have to repeat myself.

## 2. Problem

v2 forgets everything the moment a session expires. Every day I re-explain who I
am, what I am working on and how I want answers. It cannot answer "what did we
discuss about annotation last week?" because nothing outlives the 120 s session.

## 3. User

Me, single user, no accounts. Same voice-in, voice-out laptop setup as v2.

## 4. v3 scope (in)

### Profile

The profile is a fixed set of named slots, not a loose pile of facts. The slots
are defined in config/profile_schema.yaml, not in code, so a different kind of
user gets a different schema without a Python change. Values live in
data/profile.yaml and are hand-editable.

Default slots: identity, goal_now, goal_mid, goal_long, interests, exploring,
understanding, skillset, style, constraints.

The three goal horizons (about 1 month, about 6 months, multi-year) let the
assistant weigh advice: the same question gets a different answer depending on
what is urgent now.

Setup asks six slots only: identity, goal_now, goal_long, exploring, style,
constraints. The rest start empty and fill over the first week.

The whole profile is in every prompt, so it is capped at 40 lines. Going over
the cap is an error, not a silent truncation.

goal_now carries a set_on date. Over 31 days old, the assistant says once per
session that it may be stale and asks. It never edits the goal itself.

The assistant may propose a slot update and must ask before writing. It never
edits a slot silently.

### Memory

- A memory item is one key point of at most about 12 words, with a type (fact
  about me, project, preference, session summary) and a date. Never a transcript.
- "Remember that ..." stores one item and speaks it back.
- "Forget ..." deletes the matching item and nothing else. On more than one
  match it asks which, and deletes nothing until answered.
- Recall by question: "what did we discuss about annotation last week?", "what
  are my goals?". A named time filters the search by date.
- "List my memories" speaks up to 5, most recent first.
- "Wipe my memories" asks back for the phrase "yes wipe everything"; only an
  exact match wipes.
- A session writer runs when a session ends and keeps 0 to 3 key points. It
  applies a salience rule - keep only what would still matter in a month -
  deciding whether a point is worth keeping before deciding how to word it. It
  speaks only how many ("Noted two things."), never the contents.
- The writer never merges a new item onto an existing one unless it is the same
  thing. This is a real failure mode, not a hypothetical: see issue #116, where
  the v2 concept logger filed "attention in transformers" and "overfitting"
  under the existing name "lora fine-tuning".
- A frozen recall test against a seeded store.

### Retrieval

Retrieval sits behind one interface, search(query, k) -> items, so the ranking
backend can be replaced without touching anything that calls it.

v3 implements that interface with SQLite FTS5 full-text search. It adds no
dependency: FTS5 is built into SQLite. Items are short and the store is small,
so word-overlap search is expected to be enough.

A local embedding model is the named fallback, not the plan. It is added only
if the recall eval misses its target, and only then, using the failing
questions as the reason. If it is needed, it runs locally on CPU through
onnxruntime, not through torch.

## 5. Out of scope

- Embeddings and a vector store, unless the recall eval forces them
- Compaction, merging near-duplicates, monthly rollups (v4)
- A web page for editing the profile (v4 local dashboard)
- Goal carry-over, postpone and cancel workflow (v4 planner)
- Habits, schedule, recurring reminders (v4)
- Cloud, Postgres (v5)
- Open-source LLM, STT and TTS swaps (v6)
- Speaker identification (single user assumed)
- Editing an item in place (forget it, then say it again)

## 6. Privacy and prompt size

Only the profile and the memories retrieved for the current question go to the
model. This is a scaling rule first and a privacy rule second: sending the whole
store makes the prompt grow without limit as the store grows, which raises
latency and lowers recall quality. It stays true when the model becomes local.

Search runs entirely on the laptop, so no memory text leaves it to be ranked.
No memory content ever reaches Tavily; a web_search carries the query only.
"Forget" and "wipe" are real deletes, not hidden flags. data/assistant.db stays
gitignored; the eval uses its own seeded store, never mine.

## 7. Success criteria and constraints

Proposed targets; the final ones are in spec.md.

| Metric | Target |
| --- | --- |
| Right memory in top 5 | >= 90% of 20 recall questions |
| Recall answer correct | >= 17 of 20 |
| "Remember that ..." stored correctly (<= 12 words, right type) | >= 9 of 10 |
| "Forget ..." deletes the right item and nothing else | 5 of 5 |
| Invents a memory I never stated | 0 of 10 |
| Merges a near-miss pair that is not the same thing | 0 of 5 |
| Profile slots filled correctly from setup answers | 6 of 6 |
| Items stored after 10 sessions (bloat check) | <= 15 |
| Auto-writer points I judge useful | >= 7 of 10 sessions |
| Latency | <= 5.3 s median |
| v1 and v2 regression | A re-run still meets every v1 and v2 target |

Two targets are deliberately absolute. "Forget" gets no passing band because
deleting the wrong memory is worse than failing to delete. Invented memories is
0 of 10 because one confident false memory costs trust in the whole feature.

The auto-writer metric is scored by a rule written before the run, not by
judgement on the day: a point is useful if it is true, specific to the session,
and worth recalling a week later. A point that is vague, already in the profile,
or a restatement of the question is not. Score it immediately after each
session, never batched at the end.

The 5.3 s latency target is the v2 Look median of 4.3 s measured on this machine
on 2026-10-20, plus 1 s. It is not derived from the old laptop's numbers.

Retrieval decision point: after the first recall run, if "right memory in top 5"
is below 90%, I look at the failing questions and decide then whether to add a
local embedding model. Until that run, v3 adds no dependency.

Constraints:

- Gemini free tier: 15 requests per minute, 500 per day. The session writer adds
  one call per session, so a v3 eval costs more than v2's did.
- Compute: RTX 4060 Laptop GPU (8 GB VRAM), holding Whisper. Retrieval uses no
  GPU.
- No new dependency in v3. FTS5 ships with SQLite.
- Answers stay at most 3 sentences and 60 words.
- Laptop only; no screen output.
- No new dependency without my approval.

## 8. Deliverables

- Tag v0.3.0 on main with the v3 evaluation results.
- A frozen recall set eval/questions_v3.json, its seeded store, and the final
  report in eval/results/.
- README updated for v3: the memory commands, what is stored, how to wipe.
