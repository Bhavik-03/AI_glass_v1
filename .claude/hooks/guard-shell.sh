#!/usr/bin/env bash
# Runs BEFORE every shell command Claude wants to run. Exit 2 = block; the message goes to Claude.
# Bash port of guard-shell.ps1: same rules, same exit codes. Matching ignores case, like -match.

block() { echo "Blocked by guard-shell: $1" >&2; exit 2; }

# Fail closed: without jq the command can't be read, and exit 1 would let it through.
command -v jq >/dev/null || block "jq is not installed, so the command cannot be checked"
in=$(cat)                                                   # event details (JSON on stdin)
cmd=$(jq -r '.tool_input.command // ""' <<<"$in") || block "hook input is not valid JSON"
cwd=$(jq -r '.cwd // ""' <<<"$in")
# Run our git checks in Claude's folder; elsewhere they would see another repo's branch.
# `cd ""` succeeds in bash and stays put, so an empty cwd is refused explicitly.
[[ -n $cwd ]] && cd "$cwd" 2>/dev/null || block "cwd is unusable ('$cwd'); git checks cannot run"

has() { grep -qiP -e "$1" <<<"$cmd"; }                      # PCRE, like .NET regex
current=$(git branch --show-current 2>/dev/null)

# True when one `git push ...` command would update main on the remote.
pushes_main() {
    local -a words rest
    read -ra words <<<"$1"
    words=("${words[@]:2}")                                 # drop "git push"
    local w spec dst
    for w in "${words[@]}"; do
        [[ ${w,,} == --all || ${w,,} == --mirror ]] && return 0
        [[ $w != -* ]] && rest+=("$w")                      # remote, then refspecs
    done
    if (( ${#rest[@]} <= 1 )); then                         # no refspec: pushes the current branch
        [[ ${current,,} == main ]]
        return
    fi
    for spec in "${rest[@]:1}"; do
        while [[ $spec == +* ]]; do spec=${spec#+}; done      # +ref is a force push
        dst=${spec##*:}
        [[ ${dst,,} == head ]] && dst=$current
        dst=${dst,,}
        [[ ${dst#refs/heads/} == main ]] && return 0
    done
    return 1
}

# Secrets: .env (but .env.example is fine) and firmware config.h (config.example.h is fine)
has '\.env(?!\.example)\b|config\.h\b' && block "touches secrets (.env or config.h)"

# Git safety rules from git-workflow
has 'git\s+push\b.*(--force|\s-f\b)' && block "force push is never allowed"
has '--no-verify' && block "--no-verify is not allowed"
has 'git\s+add\s+(-A|--all|\.)(\s|$|;)' && block "stage files by name, not git add -A or git add ."
while IFS= read -r part; do                                 # check each chained command on its own
    if grep -qiP '^\s*git\s+push\b' <<<"$part" && pushes_main "$part"; then
        block "never push to main; use /ship-milestone"
    fi
done < <(sed -E 's/;|&&|\|\||\|/\n/g; s/\r$//' <<<"$cmd")
if has 'git\s+commit\b'; then
    [[ ${current,,} == main ]] && block "never commit on main; use the milestone branch"
fi

# Tests must pass before any commit
if has 'git\s+commit\b'; then
    py=.venv/bin/python
    if [[ -e $py ]]; then
        "$py" -m pytest -q &>/dev/null                      # run all tests, hide output
        rc=$?
        [[ $rc == 0 || $rc == 5 ]] || block "pytest is failing; fix tests before committing"
    fi                                                      # 5 = no tests yet
fi
exit 0                                                      # no match: normal permission flow
