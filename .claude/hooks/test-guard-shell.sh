#!/usr/bin/env bash
# Sends example commands through guard-shell.sh and checks each is blocked or allowed.
# Run: bash .claude/hooks/test-guard-shell.sh
guard=$(dirname "$(realpath "$0")")/guard-shell.sh
repo=$(mktemp -d)
git init -q -b main "$repo"                     # throwaway repo, so the current branch can be set
trap 'rm -rf "$repo"' EXIT
failed=0
total=0

# Prints PASS/FAIL for one case. Exit 2 = block, 0 = allow; anything else is reported as rc<N>.
report() {
    local expect=$1 rc=$2 label=$3 got mark=PASS
    case $rc in 2) got=block ;; 0) got=allow ;; *) got=rc$rc ;; esac
    [[ $got == "$expect" ]] || { mark=FAIL; ((failed++)); }
    ((total++))
    printf '%s  %-5s %s\n' "$mark" "$got" "$label"
}

check() {  # expect, branch, command
    git -C "$repo" symbolic-ref HEAD "refs/heads/$2"
    jq -nc --arg c "$3" --arg d "$repo" '{tool_input:{command:$c},cwd:$d}' \
        | bash "$guard" &>/dev/null
    report "$1" $? "on $(printf '%-16s' "$2") ${3//$'\n'/\\n}"
}

check_input() {  # expect, label, raw stdin, PATH for the guard
    printf '%s' "$3" | PATH=$4 "$BASH" "$guard" &>/dev/null
    report "$1" $? "$2"
}

F=feature/m1-demo
# push to main (same 18 cases as test-guard-shell.ps1)
check block $F   'git push origin main'
check block $F   'git push origin HEAD:main'
check block $F   'git push origin feature/m1-demo:refs/heads/main'
check block main 'git push'
check block main 'git push -u origin'
check block main 'git push origin HEAD'
check block $F   'git push --force origin main'
check block $F   'git push -f origin main'
check block $F   'git push origin +main'
check block $F   'git status; git push origin main'
check allow $F   'gh pr create --base main --title "M1 (v1): Server skeleton"'
check allow $F   'git checkout main'
check allow main 'git pull origin main'
check allow $F   'git push -u origin feature/m1-maintenance'
check allow $F   'git push origin fix-main-docs'
check allow $F   'git push'
check allow main 'git push origin v0.1.0'
check allow $F   'git switch main; git pull'
# secrets
check block $F   'cat .env'
check block $F   'cat ./server/.env'
check block $F   'grep KEY .ENV'
check block $F   'echo hi > .env'
check block $F   'cp .env.example .env'
check block $F   'cat firmware/glasses/config.h'
check allow $F   'cat .env.example'
check allow $F   'cat firmware/glasses/config.example.h'
check allow $F   'ls -la'
# other rules
check block $F   'git commit --no-verify -m x'
check block $F   'git add -A'
check block $F   'git add .'
check block $F   'git add --all'
check block $F   'git add .; git status'
check allow $F   'git add server/main.py'
check allow $F   'git add .claude/hooks/guard-shell.sh'
check block $F   'GIT PUSH ORIGIN MAIN'
check block $F   $'ls\ngit push origin main'
check block $F   'git push origin feat && git push origin main'
check block main 'git commit -m x'
check allow $F   'git commit -m x'
check block $F   'git push --mirror'
# fail closed when the input can't be trusted
check_input block 'input is not JSON' 'not json' "$PATH"
check_input block 'jq is not installed' '{}' /nonexistent
check_input block 'cwd is missing' '{"tool_input":{"command":"ls"}}' "$PATH"
check_input block 'cwd is empty' '{"tool_input":{"command":"ls"},"cwd":""}' "$PATH"
check_input block 'cwd does not exist' \
    '{"tool_input":{"command":"ls"},"cwd":"/nonexistent/dir"}' "$PATH"

echo "$((total - failed)) of $total passed"
exit $((failed > 0))
