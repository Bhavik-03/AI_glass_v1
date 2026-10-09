# Runs BEFORE every shell command Claude wants to run. Exit 2 = block; the message goes to Claude.
$in  = [Console]::In.ReadToEnd() | ConvertFrom-Json        # event details from Claude Code (JSON on stdin)
$cmd = [string]$in.tool_input.command                       # the command Claude wants to run
Set-Location $in.cwd                                        # run our git checks in Claude's folder

function Block($why) { [Console]::Error.WriteLine("Blocked by guard-shell: $why"); exit 2 }

# True when one `git push ...` command would update main on the remote.
function Test-PushesMain($push) {
    $words = @($push.Trim() -split '\s+' | Select-Object -Skip 2)          # drop "git push"
    if ($words -contains '--all' -or $words -contains '--mirror') { return $true }
    $rest = @($words | Where-Object { $_ -notlike '-*' })                 # remote, then refspecs
    $current = git branch --show-current
    if ($rest.Count -le 1) { return $current -eq 'main' }                 # no refspec: pushes the current branch
    foreach ($spec in $rest[1..($rest.Count - 1)]) {
        $spec = $spec.TrimStart('+')                                       # +ref is a force push
        $dst  = if ($spec -match ':') { $spec.Split(':')[-1] } else { $spec }
        if ($dst -eq 'HEAD') { $dst = $current }
        if (($dst -replace '^refs/heads/', '') -eq 'main') { return $true }
    }
    return $false
}

# Secrets: .env (but .env.example is fine) and firmware config.h (config.example.h is fine)
if ($cmd -match '\.env(?!\.example)\b|config\.h\b')               { Block "touches secrets (.env or config.h)" }

# Git safety rules from git-workflow
if ($cmd -match 'git\s+push\b.*(--force|\s-f\b)')                   { Block "force push is never allowed" }
if ($cmd -match '--no-verify')                                      { Block "--no-verify is not allowed" }
if ($cmd -match 'git\s+add\s+(-A|--all|\.)(\s|$|;)')                { Block "stage files by name, not git add -A or git add ." }
foreach ($part in $cmd -split ';|&&|\|\||\||\r?\n') {                 # check each chained command on its own
    if ($part -match '^\s*git\s+push\b' -and (Test-PushesMain $part)) { Block "never push to main; use /ship-milestone" }
}
if ($cmd -match 'git\s+commit\b') {
    if ((git branch --show-current) -eq 'main')                     { Block "never commit on main; use the milestone branch" }
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
