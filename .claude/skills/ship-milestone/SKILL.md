---
name: ship-milestone
description: "Ship a finished milestone: final checks, push, PR, merge, close the GitHub milestone, and tag the version after its last milestone."
disable-model-invocation: true
argument-hint: "[M<N>]"
allowed-tools: >-
  Bash(git status *) Bash(git log *) Bash(git diff *) Bash(git add *) Bash(git commit *)
  Bash(git push -u origin feature/*) Bash(git switch main) Bash(git pull) Bash(gh pr *) Bash(gh api *)
  Bash(git tag -a v*) Bash(git push origin v*)
  PowerShell(git status *) PowerShell(git log *) PowerShell(git diff *) PowerShell(git add *) PowerShell(git commit *)
  PowerShell(git push -u origin feature/*) PowerShell(git switch main) PowerShell(git pull) PowerShell(gh pr *) PowerShell(gh api *)
  PowerShell(git tag -a v*) PowerShell(git push origin v*)
---
Ship milestone $ARGUMENTS (default: the milestone of the current `feature/m<N>-*` branch), following the git-workflow skill. Stop at the first failed check, report why, and never merge.

1. Check: on the milestone's `feature/m<N>-*` branch; `git status --short` is empty; every M<N> task in `docs/plan.md` is ticked.
2. Use the test-runner subagent and wait for its report. Continue only with 0 failed, 0 errors and RUFF clean.
3. Set M<N> to done in `docs/plan.md` and commit `docs(plan): mark M<N> done`.
4. Push the branch and open the PR, with one `Closes #<issue>` line per task issue from plan.md.
5. Merge with `gh pr merge --merge --delete-branch`, then `git switch main`, then `git pull`.
6. Close the GitHub milestone.
7. If M<N> is the last milestone of its version in `docs/roadmap.md`, tag the version on the merged main, using the tag from roadmap.md (v1 → v0.1.0):
   `git tag -a v0.1.0 -m "v1: Voice assistant"`, then `git push origin v0.1.0`.
   Don't create a GitHub release, archive the docs or write the next version's docs; tell me those are next.
8. Report: PR link, commits merged, issues closed, and the tag pushed if any.
