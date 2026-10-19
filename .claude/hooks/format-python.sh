#!/usr/bin/env bash
# Runs AFTER every file edit. Formats .py files, then lints them; lint problems go back to Claude.
# Bash port of format-python.ps1: same rules, same exit codes.

# Fails OPEN on purpose (unlike guard-shell.sh): a skipped format is harmless and the edit is done.
file=$(jq -r '.tool_input.file_path // ""') || exit 0
[[ ${file,,} == *.py ]] || exit 0                           # only Python files
root=$(realpath -m -s "$CLAUDE_PROJECT_DIR")/
full=$(realpath -m -s "$file")
[[ ${full,,} == "${root,,}"* ]] || exit 0                   # only files inside this project
[[ ${full,,} == "${root,,}.venv/"* ]] && exit 0             # never the venv's packages
py=$root.venv/bin/python
[[ -e $py ]] || exit 0                                      # venv not created yet: skip quietly
"$py" -m ruff format --quiet "$full" >/dev/null             # fix formatting in place
if ! lint=$("$py" -m ruff check "$full" 2>&1); then         # find lint problems (no auto-fix)
    echo "$lint" >&2                                        # Claude sees these lines…
    exit 2                                                  # …because exit 2 shows stderr
fi
exit 0
