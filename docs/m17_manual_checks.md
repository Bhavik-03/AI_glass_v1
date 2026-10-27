# M17 manual voice checks (session writer)

Real server, real client, real Gemini, your voice. Do not run any of this by accident: these checks write to your real memory store unless you restore the backup afterwards.

Facts found read-only before writing this list:
- Your real `data/assistant.db` had no `kind` column yet, so the first server start migrates it. That is why the backup comes first.
- It had 3 memory rows and no pending reminders.
- `logs/queries.jsonl` had no session_writer line yet.

## Setup, once

All commands run from `/home/bhavik/AI_glass_v1`, with the server and client stopped.

Back up your profile and database:

    cp -p data/profile.json data/profile.json.bak-m17
    cp -p data/assistant.db data/assistant.db.bak-m17

Restore them afterwards (stop the server and client first):

    cp -p data/profile.json.bak-m17 data/profile.json
    cp -p data/assistant.db.bak-m17 data/assistant.db

Start the server and the client in two terminals:

    .venv/bin/python -m server.main
    .venv/bin/python -m client_pc.client

Keys: Right Alt = voice, Right Ctrl = voice plus a screenshot. These checks use Right Alt only. Stop either program with Ctrl+C.

If the first thing you hear is a setup question, say "stop setup" with Right Alt once.

## The three look-commands

Run these in a third terminal, from the repo folder. None of them reads `.env` or prints an API key, and the log redacts keys. Never run `printenv`, `env` or `cat .env` while checking.

Memory rows, newest first (note the top id before and after each check):

    .venv/bin/python -c "import sqlite3; c=sqlite3.connect('data/assistant.db'); [print(r) for r in c.execute('SELECT id, type, created_at, text FROM memories ORDER BY id DESC LIMIT 8')]"

Last writer line:

    grep '"event": "session_writer"' logs/queries.jsonl | tail -n 1 | .venv/bin/python -m json.tool

Notice rows, newest first:

    .venv/bin/python -c "import sqlite3; c=sqlite3.connect('data/assistant.db'); [print(r) for r in c.execute(\"SELECT id, text, status FROM reminders WHERE kind='notice' ORDER BY id DESC LIMIT 5\")]"

How to read the writer line: `turns` is how many questions the session had, `points_returned` is what the writer returned, `rows_added` is what was stored, `points_too_long` and `points_rejected` count rejected points, `dropped` lists points the guard removed (each with its direction, scores and, for an ungrounded one only, its text), `error` is null when it worked.

## Rules for every check

- Wait for each spoken answer to finish before the next key press.
- Press nothing during a wait. A new question within 120 s joins the same session.
- Leave at least 150 s between checks so two sessions do not merge.
- Timing: the session ends 120 s after your last question. The client polls every 10 s and the writer call takes about 2 s, so expect any "Noted..." line about 125 to 140 s after your last question. Wait a full 150 s before calling it silence.
- The client terminal also prints "Reminder: Noted..." when it speaks. That is the known cosmetic effect of the unchanged client, not a defect.
- Defect means something is wrong and must be fixed. Finding means a known tendency that I want recorded, not fixed now.

## Check 0: migration (no writer, no waiting)

Say (Right Alt): "What are my reminders?"

After the server has started, run:

    .venv/bin/python -c "import sqlite3; print([r[1] for r in sqlite3.connect('data/assistant.db').execute('PRAGMA table_info(reminders)')])"

Pass: the list ends with 'kind', the server is running, and the answer is normal (you have no pending reminders).

Defect: the server fails to start, the command shows no 'kind', or the question errors.

## Check 1: one real fact and one thing I did not say

Say (Right Alt each, one after the other):
1. "I've decided to keep all my project notes in Obsidian instead of Notion."
2. "What note-taking setup would you suggest for someone like me?"

Wait 150 s and press nothing. You should hear only "Noted one thing."

Look: run all three look-commands.

Pass: one new memory row about Obsidian instead of Notion, 12 words or fewer. The writer line shows turns 2, rows_added 1 and error null. The row holds nothing you did not say and nothing from the second question.

Defect: any row stating something you never said; a row over 12 words; the spoken line giving contents instead of only a count; a stored row with no spoken notice.

About "a thing I did not say": you cannot force the assistant to attribute something to you. If its answer says something about you and the writer returns it, the writer line's `dropped` list shows it with direction `ungrounded` and its text, which is the guard holding. If `dropped` is empty, the guard was not exercised in this check. Tell me which it was.

## Check 2: the "Noted two things." notice

Say (Right Alt each, one after the other):
1. "For my weather station project I've decided to log temperature readings to a CSV file."
2. "For the same project I've decided the dashboard will be a Streamlit app."
3. "What is a good sampling interval for outdoor temperature?"

Wait 150 s. You should hear "Noted two things." once.

Look: run all three look-commands.

Pass: two new rows with different wording, each 12 words or fewer, and the spoken count matches rows_added.

Finding (not a defect): one merged row, or only one row. That is the known under-keeping tendency. Tell me which happened.

Defect: a spoken count that differs from rows_added, a row over 12 words, invented content, or the notice spoken twice.

## Check 3: a session after which nothing is spoken

Say (Right Alt each, one after the other):
1. "How's your day going?"
2. "Tell me a joke about transistors."

Wait 150 s. You should hear nothing at all.

Look: the writer line and the memory rows and the notice rows.

Pass: silence; a new writer line with rows_added 0 and error null; no new memory row; no new notice row.

Defect: any speech, any new row, no writer line at all, or a non-null error.

## Check 4: client closed before the writer runs (known limit)

4a, server stays running.

Say (Right Alt): "I've decided to power the weather station from a 12 volt solar panel."

When the answer ends, press Ctrl+C in the client terminal within about 20 s. Leave the server running. Wait 180 s. Run the writer-line and memory commands: there should be no new writer line and no new row. Then restart the client:

    .venv/bin/python -m client_pc.client

Within about 10 to 20 s you should hear "Noted one thing."

Expected from the code: the expired session waits in the server's memory and is written on the first poll after the client returns, late. `docs/design.md` says the points are "lost", which understates it.

Pass: nothing is written while the client is closed, and the write happens after the restart.

Defect: a write while no client is running, a crash, or a lost session with the server still up. Please tell me whether the late write happened, so the design wording can be corrected if it did.

4b, the real loss (server restarted).

Say (Right Alt): "I've decided to name the weather station project Skylog."

When the answer ends, stop the client (Ctrl+C) and then stop the server (Ctrl+C). Wait 150 s. Start the server, then the client.

Pass: nothing is ever written for that session and nothing breaks. The buffer lives in server memory, so a server restart loses it.

Defect: a crash, or a stale session written after the restart.

## Check 5: profile restatement is not stored

First look at your own `data/profile.json` yourself (cat it). Then say, in words different from the file:
1. "Just so you know, <your identity slot, reworded>."
2. "And my long term goal is <your long-term goal slot, reworded>."
3. "What is a good first step for that?"

Wait 150 s. You should hear nothing.

Look: run all three look-commands.

Pass: no new memory row and nothing spoken. The writer line has rows_added 0, and either points_returned 0 (the instruction held) or a dropped entry with direction `known` and no text (the guard held). Tell me which.

Defect: a stored row that restates your profile, or any spoken notice.

## When you are done

Send me the writer line and the memory rows for each check. Then restore your profile and database with the restore commands in Setup, with the server and client stopped.
