---
name: plan-milestone
description: Plan the next milestone from the docs into docs/plan.md, a GitHub milestone and issues.
disable-model-invocation: true
argument-hint: "[M<N>]"
---
Plan milestone $ARGUMENTS (default: the first milestone in `docs/plan.md` without tasks).

1. Be on `main` with an empty `git status --short`, else stop. Run `git pull`.
2. Read `docs/brief.md`, `docs/spec.md`, `docs/design.md`, plus `docs/expense_v1.md` for Phase B work. Read `docs/plan.md` if it exists.
3. If `docs/plan.md` doesn't exist, first propose the milestone list: ID, phase, one-line goal, FRs. Every FR-1…FR-11 and every quality target must land in a milestone. Wait for my approval.
4. Break the target milestone into tasks. Each task: one commit, ≤ 3 files, doable in one /build-task run, dependencies first. Copy "done when" from the spec's acceptance criteria; never invent criteria. If the docs leave a decision open, ask me instead of choosing.
5. Show me the task table and wait for approval or edits. Write nothing before approval.
6. Following the git-workflow skill: create branch `feature/m<N>-<slug>`, the GitHub milestone, and one issue per task.
7. Write `docs/plan.md` in this format, with the issue numbers, and commit `docs(plan): plan M<N>`. Don't push.

```markdown
# Plan: AI Assistant Glasses v1

## M1: Server skeleton | Phase A | in progress
Goal: <one line> · GitHub milestone: #<n>

| Task | FR | Files | Done when | Test | Issue | Done |
| --- | --- | --- | --- | --- | --- | --- |
| M1-T1 | FR-9 | server/config.py, server/main.py | GET /health returns 200 {"status": "ok", "model": ...} | pytest | #1 | [ ] |

Manual checks: <criteria needing hardware or a human>

## M2: <name> | Phase A | planned
Goal: <one line> · FRs: <list> · Tasks: not planned yet
```
Status is planned, in progress or done. Test is pytest, compile or manual.
