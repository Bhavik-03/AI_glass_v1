# Runs AFTER every file edit. Formats .py files, then lints them; lint problems go back to Claude.
$in   = [Console]::In.ReadToEnd() | ConvertFrom-Json
$file = [string]$in.tool_input.file_path                     # absolute path, with backslashes on Windows
if ($file -notlike '*.py') { exit 0 }                         # only Python files
$root = [IO.Path]::GetFullPath($env:CLAUDE_PROJECT_DIR).TrimEnd('\') + '\'
$full = [IO.Path]::GetFullPath($file)
$ic   = [StringComparison]::OrdinalIgnoreCase
if (-not $full.StartsWith($root, $ic)) { exit 0 }             # only files inside this project
if ($full.StartsWith($root + '.venv\', $ic)) { exit 0 }       # never the venv's packages
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { exit 0 }                          # venv not created yet: skip quietly
& $py -m ruff format --quiet $full | Out-Null                 # fix formatting in place
$lint = & $py -m ruff check $full 2>&1                        # find lint problems (no auto-fix)
if ($LASTEXITCODE -ne 0) {
    [Console]::Error.WriteLine(($lint | Out-String))          # Claude sees these lines…
    exit 2                                                    # …because exit 2 on PostToolUse shows stderr to Claude
}
exit 0
