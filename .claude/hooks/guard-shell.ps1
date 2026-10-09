# Runs BEFORE every shell command Claude wants to run. Exit 2 = block; the message goes to Claude.
$in  = [Console]::In.ReadToEnd() | ConvertFrom-Json        # event details from Claude Code (JSON on stdin)
$cmd = [string]$in.tool_input.command                       # the command Claude wants to run
Set-Location $in.cwd                                        # run our git checks in Claude's folder

function Block($why) { [Console]::Error.WriteLine("Blocked by guard-shell: $why"); exit 2 }

# Secrets: .env (but .env.example is fine) and firmware config.h (config.example.h is fine)
if ($cmd -match '\.env(?!\.example)\b|config\.h\b')               { Block "touches secrets (.env or config.h)" }

# Git safety rules from git-workflow
if ($cmd -match 'git\s+push\b.*(--force|\s-f\b)')                   { Block "force push is never allowed" }
if ($cmd -match '--no-verify')                                      { Block "--no-verify is not allowed" }
if ($cmd -match 'git\s+add\s+(-A|--all|\.)(\s|$|;)')                { Block "stage files by name, not git add -A or git add ." }
if ($cmd -match 'git\s+push\b.*(\s|:)main(\s|$)')                   { Block "never push to main; use /ship-milestone" }
$pushTag = $cmd -match '^\s*git\s+push\s+origin\s+v\d+\.\d+\.\d+\s*$'  # /ship-milestone pushes the version tag from main
if ($cmd -match 'git\s+(commit|push)\b' -and -not $pushTag) {
    if ((git branch --show-current) -eq 'main')                     { Block "never commit or push on main; use the milestone branch" }
}

# Tests must pass before any commit
if ($cmd -match 'git\s+commit\b') {
    $py = '.venv\Scripts\python.exe'
    if (Test-Path $py) {
        & $py -m pytest -q *> $null                                 # run all tests, hide output
        if ($LASTEXITCODE -notin 0, 5) { Block "pytest is failing; fix tests before committing" }  # 5 = no tests yet
    }
}
exit 0                                                              # nothing matched: normal permission flow