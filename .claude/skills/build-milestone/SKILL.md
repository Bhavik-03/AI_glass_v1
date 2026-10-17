---
name: build-milestone
description: "Build every unticked plan.md task of one milestone in order, each through /build-task."
disable-model-invocation: true
argument-hint: "M<N>"
---
Build milestone $ARGUMENTS. If a step can't be done, stop and report why.

1. Check we are on the milestone's branch (`feature/m<N>-<slug>`) and `git status --short` is empty, else stop.
2. Read `docs/plan.md` and list the unticked tasks of $ARGUMENTS in table order.
3. For each task in order: read `.claude/skills/build-task/SKILL.md` and follow every step of it for that task exactly (tests first, runner, code, reviewer, tick, one commit). Skip tasks whose Test is "manual" and list them at the end.
4. Stop at once if a task fails 3 test rounds, gets BLOCKED twice, needs a new dependency, or needs a file outside its row. Report which task and why.
5. At the end, report one line per task: ID, commit hash, PASS or STOPPED (skipped manual tasks listed separately).

Never push or merge. Never edit docs other than ticking tasks in `docs/plan.md`.
