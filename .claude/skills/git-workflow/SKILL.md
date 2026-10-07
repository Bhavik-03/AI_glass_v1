---
name: git-workflow
description: Git branch, commit, PR, release and GitHub milestone/issue conventions for this repo. Use when committing, branching, opening or merging a PR, tagging a release, or creating GitHub issues or milestones.
user-invocable: false
---
# Git and GitHub workflow

Shell is PowerShell: one command per line, never `&&`.

## Branches
- One branch per milestone, created by /plan-milestone from an up-to-date main, one command per line:
  `git switch main`, `git pull`, `git switch -c feature/m<N>-<slug>`
- Every change, plan.md included, goes on the milestone branch. Never commit to main.
- Never `git push --force`, `--amend` a pushed commit, or `--no-verify`.

## Commits
- One commit per task, after its tests pass and review says PASS; tests and code in the same commit.
- Format: `<type>(<scope>): <summary> (FR-<n>)`, imperative, ≤ 72 chars.
  - types: feat, fix, test, refactor, docs, chore
  - scopes: server, client, firmware, tests, docs, repo
  - example: `feat(server): add /health endpoint (FR-9)`
- Stage files by name (`git add server/main.py tests/test_server.py`), never `git add -A` or `git add .`.
- Run `git status` first: `.env`, `config.h`, `logs/`, `.venv/`, `models/` must never appear.

## GitHub (gh CLI only)
- gh works on the repo of the current folder (the `origin` remote). Never type an owner or repo name; use the literal `{owner}/{repo}` placeholders in `gh api` paths.
- Milestone = one plan.md milestone, titled `M<N>: <name>`.
  - create: `gh api "repos/{owner}/{repo}/milestones" -f title="M1: Server skeleton" -f description="<goal>"`
  - find its number: `gh api "repos/{owner}/{repo}/milestones" --jq '.[] | [.number, .title] | @tsv'`
  - close: `gh api -X PATCH "repos/{owner}/{repo}/milestones/<number>" -f state=closed`
- Issue = one plan.md task:
  `gh issue create --title "[M1-T1] /health endpoint (FR-9)" --body "<done when>" --milestone "M1: Server skeleton"`
- PR = one milestone:
  `git push -u origin feature/m<N>-<slug>`
  `gh pr create --base main --title "M1: Server skeleton" --milestone "M1: Server skeleton" --body "<body>"`
  - body: what the milestone delivers, a table of task → FR → tests, one `Closes #<issue>` line per task, last test-runner summary.
- Merge: `gh pr merge --merge --delete-branch`, then `git switch main`, then `git pull`.

## Releases (only when I ask)
- Tag at the end of a phase: v0.1.0 = Phase A, v1.0.0 = Phase B.
- `gh release create v0.1.0 --target main --title "v0.1.0: Phase A" --notes "<what works, eval results>"`
