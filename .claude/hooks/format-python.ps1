# Runs AFTER every file edit. Formats .py files, then lints them; lint problems go back to Claude.
$in   = [Console]::In.ReadToEnd() | ConvertFrom-Json
$file = [string]$in.tool_input.file_path                     # absolute path, with backslashes on Windows
if ($file -notlike '*.py') { exit 0 }                         # only Python files
$py = Join-Path $env:CLAUDE_PROJECT_DIR '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { exit 0 }                          # venv not created yet: skip quietly
& $py -m ruff format --quiet $file | Out-Null                 # fix formatting in place
$lint = & $py -m ruff check $file 2>&1                        # find lint problems (no auto-fix)
if ($LASTEXITCODE -ne 0) {
    [Console]::Error.WriteLine(($lint | Out-String))          # Claude sees these lines…
    exit 2                                                    # …because exit 2 on PostToolUse shows stderr to Claude
}
exit 0