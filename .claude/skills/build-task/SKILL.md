---
name: build-task
description: "Build one plan.md task end to end: tests, code, checks, review, commit."
disable-model-invocation: true
argument-hint: "M<N>-T<k>"
---
Build task $ARGUMENTS. Wait for each subagent's report before the next step. If a step can't be done, stop and report why.

1. Read the $ARGUMENTS row in `docs/plan.md` and its FR rows in `docs/spec.md`. If the row is missing or already ticked, stop.
2. Check you're on this milestone's `feature/m<N>-*` branch, else stop.
3. If Test is pytest: use the test-writer subagent with the task ID, FRs and "done when". Then use the test-runner subagent: the new tests must fail because the code is missing, not because a test is broken.
4. Implement the task yourself: only the files in the task row (ask before touching others), the least code that passes. Follow server-conventions for server/ and tests/.
5. Verify. pytest: use the test-runner subagent; fix and re-run, and stop after 3 failed rounds. compile: run the firmware compile. manual: list the manual checks for me.
6. Use the reviewer subagent with the task ID and FRs. Fix every BLOCKING item and repeat steps 5–6; stop after 2 BLOCKED rounds.
7. Tick the task in `docs/plan.md` and make one commit following git-workflow. Don't push.
8. Report (max 10 lines): files changed, tests added, test summary, review verdict, commit hash, manual checks left for me.
