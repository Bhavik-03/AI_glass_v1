# Plan: AI Assistant v3 Memory

## M13 (v3): Memory store | in progress
Goal: memories table with a FTS5 index, `search_memories(query, k, since, until)`, `find_same` with a measured threshold · GitHub milestone: #13

| Task | FR | Files | Done when | Test | Issue | Done |
| --- | --- | --- | --- | --- | --- | --- |
| M13-T1 | FR-40 | docs/plan.md (spike script not committed) | Spike results recorded here: a word-based `find_same` metric and `MEMORY_SAME_THRESHOLD` measured on the spike's own pairs, written for it and never placed in `questions_v3.json`. The pairs are near-miss ones that must stay two rows, plus same-thing pairs in different wording that must be recognised as the same. The chosen metric and value, and where they fail, are recorded | manual | #120 | [ ] |
| M13-T2 | FR-32 | server/config.py, server/store.py (+ tests/test_store.py) | A `memories` table (id, text, type fact/project/preference/session, created_at) created at startup, with `MEMORY_MAX_WORDS` (12) from config. `add_memory` stores a row with all four fields set. An item over the word limit is rejected before storage and the caller is told. The table survives a restart (re-`init()` on the same temp DB) | pytest | #121 | [ ] |
| M13-T3 | FR-37 | server/store.py (+ tests/test_store.py) | A FTS5 index over `memories.text`, kept in sync with inserts and deletes by triggers (`DELETE FROM memories` empties it). `search_memories(query, k)` returns at most `k` items, best first. A spoken question with words not in the item ("what did we discuss about annotation") still returns the item containing "annotation". A question containing FTS5 syntax characters (quotes, apostrophes, hyphens) does not raise (derived from CLAUDE.md: the server never crashes) | pytest | #122 | [ ] |
| M13-T4 | FR-38 | server/store.py (+ tests/test_store.py) | `since` and `until` filter by `created_at` before ranking. With one matching item inside the window and one outside it, only the inside one is returned, whether the outside one is before `since` or after `until`. The same question with no time returns both. An unparseable `since` or `until` means no filter, not no results | pytest | #123 | [ ] |
| M13-T5 | FR-40 | server/config.py, server/store.py (+ tests/test_store.py) | `find_same(text)` uses the T1 metric and `MEMORY_SAME_THRESHOLD`. With "LoRA fine-tuning" stored, adding "attention in transformers" makes a new row and leaves the first unchanged. The same point added again in different wording adds no row, leaves the stored item (text and `created_at`) unchanged, and returns the existing item with `new` false | pytest | #124 | [ ] |

Manual checks: none. M13 has no user-facing path; the first spoken use is in M14.

## M14 (v3): Memory commands | planned
Goal: `remember`, `search_memories` and `forget` tools, the wipe phrase in `main.py`, list and recall behaviour, the instruction rules, `memories_used` in the log, and a local ranking harness that makes the embedding decision · FRs: FR-33, FR-34, FR-35, FR-36, FR-37 · Tasks: not planned yet

Planned task, FR-37: `eval/rank_probe.py` (committed; CLAUDE.md lists it) loads `eval/seed_v3.json`, calls `search_memories(query, 5)` for 20 hand-written probe questions kept as a constant inside the script, and reports the top-5 hit rate. Composition rule: at least 8 of the 20 share no content word with the item they should retrieve (for example "the thing about making models smaller" retrieving a "quantization" item); the other 12 are realistic mixed phrasings. The probes are written before the harness is first run and are not edited afterwards, and are never placed in `questions_v3.json`. A rate below 90% is the signal to propose the local embedding model (a new dependency, needs approval); the decision is recorded here as the task's outcome. It measures ranking only: whether Gemini then uses what it is given is a separate failure that only the M18 run catches. Re-run it whenever the search implementation changes. Order it first in M14, since it depends only on M13's `search_memories`.

## M15 (v3): Profile | planned
Goal: schema and values JSON, load errors, rendered 40-line cap at load and write, profile in every system instruction · FRs: FR-26, FR-27, FR-28 · Tasks: not planned yet

## M16 (v3): Setup and goals | planned
Goal: first-run setup, "stop setup", the stale `goal_now` line, slot-update proposals behind a yes · FRs: FR-29, FR-30, FR-31 · Tasks: not planned yet

## M17 (v3): Session writer | planned
Goal: pending-write buffer on expiry, writer call, notice rows and the `kind` column, the writer's own log line · FRs: FR-39, FR-40, FR-17 · Tasks: not planned yet

## M18 (v3): Evaluation and release | planned
Goal: frozen v3 set and seed, `record --set v3`, `run_eval_v3.py`, every quality target, v1 and v2 regression re-runs, README, tag v0.3.0 · FRs: all v3 quality targets · Tasks: not planned yet

Two tasks to plan explicitly, not as sub-points: `run_eval_v3.py` backs up and restores `data/profile.json` as well as the tables, because a run that leaves a test profile behind changes every later answer; and the writer phase, 10 sessions with no `POST /session/reset` between them, each lapsing its 120 s TTL before the poll is called, about 20 minutes of wall clock.
