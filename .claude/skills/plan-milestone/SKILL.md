---
name: plan-milestone
description: Plan the next milestone of the current version from the docs into docs/plan.md, a GitHub milestone and issues.
disable-model-invocation: true
argument-hint: "[M<N>]"
---
Plan milestone $ARGUMENTS (default: the first milestone in `docs/plan.md` without tasks).

1. Be on `main` with an empty `git status --short`, else stop. Run `git pull`.
2. Read `docs/roadmap.md` to find the current version and its milestones. Plan only milestones of the current version; if $ARGUMENTS belongs to another version, stop and say so.
3. Read `docs/brief.md`, `docs/spec.md`, `docs/design.md`, plus `docs/hardware_plan.md` only when the current version is v4 or v5. Read `docs/plan.md` if it exists. Never plan from `docs/archive/`.
4. If `docs/plan.md` has no section for the current version, first propose its milestone list: ID, one-line goal, FRs. Milestone IDs continue across versions (if the last version ended at M7, the next starts at M8). Every FR and every quality target of the current spec must land in a milestone. Wait for my approval.
5. Break the target milestone into tasks. Each task: one commit, ≤ 3 files, doable in one /build-task run, dependencies first. Copy "done when" from the spec's acceptance criteria; never invent criteria. If the docs leave a decision open, ask me instead of choosing.
6. Show me the task table and wait for approval or edits. Write nothing before approval.
7. Following the git-workflow skill: create branch `feature/m<N>-<slug>`, the GitHub milestone titled `M<N> (v<V>): <name>` (e.g. "M8 (v2): Android app"), and one issue per task.
8. Write `docs/plan.md` in this format, with the issue numbers, and commit `docs(plan): plan M<N>`. Don't push.

```markdown
# Plan: AI Assistant v1 Voice assistant

## M1 (v1): Server skeleton, config and logger | in progress
Goal: <one line> · GitHub milestone: #<n>

| Task | FR | Files | Done when | Test | Issue | Done |
| --- | --- | --- | --- | --- | --- | --- |
| M1-T1 | FR-18 | server/config.py, server/main.py | GET /health returns 200 {"status": "ok", "model": ...} | pytest | #1 | [ ] |

Manual checks: <criteria needing hardware or a human>

## M2 (v1): <name> | planned
Goal: <one line> · FRs: <list> · Tasks: not planned yet
```
Status is planned, in progress or done. Test is pytest, compile or manual. The plan's title names the current version; at the end of a version plan.md is archived with the other docs and the next version starts a new one.
