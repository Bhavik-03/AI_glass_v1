---
name: git-workflow
description: Git branch, commit, PR, version tag and GitHub milestone/issue conventions for this repo. Use when committing, branching, opening or merging a PR, tagging a version, or creating GitHub issues or milestones.
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
  - example: `feat(server): add /health endpoint (FR-18)`
- Stage files by name (`git add server/main.py tests/test_server.py`), never `git add -A` or `git add .`.
- Run `git status` first: `.env`, `config.h`, OAuth tokens, certificates, `data/` or any `.db`, `logs/`, `.venv/`, `models/` must never appear.

## GitHub (gh CLI only)
- gh works on the repo of the current folder (the `origin` remote). Never type an owner or repo name; use the literal `{owner}/{repo}` placeholders in `gh api` paths.
- Milestone = one plan.md milestone, titled `M<N> (v<V>): <name>`. IDs continue across versions (v2 starts at M8).
  - create: `gh api "repos/{owner}/{repo}/milestones" -f title="M1 (v1): Server skeleton" -f description="<goal>"`
  - find its number: `gh api "repos/{owner}/{repo}/milestones" --jq '.[] | [.number, .title] | @tsv'`
  - close: `gh api -X PATCH "repos/{owner}/{repo}/milestones/<number>" -f state=closed`
- Issue = one plan.md task:
  `gh issue create --title "[M1-T1] /health endpoint (FR-18)" --body "<done when>" --milestone "M1 (v1): Server skeleton"`
- PR = one milestone:
  `git push -u origin feature/m<N>-<slug>`
  `gh pr create --base main --title "M1 (v1): Server skeleton" --milestone "M1 (v1): Server skeleton" --body "<body>"`
  - body: what the milestone delivers, a table of task → FR → tests, one `Closes #<issue>` line per task, last test-runner summary.
- Merge: `gh pr merge --merge --delete-branch`, then `git switch main`, then `git pull`.

## Version tags
- One annotated tag per version, from roadmap.md: v1 = v0.1.0, v2 = v0.2.0, v3 = v0.3.0, v4 = v0.4.0, v5 = v1.0.0.
- /ship-milestone creates and pushes it on main after the version's last milestone is merged:
  `git tag -a v0.1.0 -m "v1: Voice assistant"`, then `git push origin v0.1.0`.
- A GitHub release only when I ask: `gh release create v0.1.0 --verify-tag --title "v0.1.0: Voice assistant" --notes "<what works, eval results>"`
