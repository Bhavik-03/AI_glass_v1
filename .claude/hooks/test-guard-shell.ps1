# Sends example commands through guard-shell.ps1 and checks each is blocked or allowed.
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File .claude\hooks\test-guard-shell.ps1
$guard = Join-Path $PSScriptRoot 'guard-shell.ps1'
$repo  = Join-Path ([IO.Path]::GetTempPath()) ("guard-test-" + [guid]::NewGuid())
git init -q -b main $repo                                    # throwaway repo, so "current branch" can be set

$cases = @(
    # expect, branch, command
    @('block', 'feature/m1-demo', 'git push origin main'),
    @('block', 'feature/m1-demo', 'git push origin HEAD:main'),
    @('block', 'feature/m1-demo', 'git push origin feature/m1-demo:refs/heads/main'),
    @('block', 'main',            'git push'),
    @('block', 'main',            'git push -u origin'),
    @('block', 'main',            'git push origin HEAD'),
    @('block', 'feature/m1-demo', 'git push --force origin main'),
    @('block', 'feature/m1-demo', 'git push -f origin main'),
    @('block', 'feature/m1-demo', 'git push origin +main'),
    @('block', 'feature/m1-demo', 'git status; git push origin main'),
    @('allow', 'feature/m1-demo', 'gh pr create --base main --title "M1 (v1): Server skeleton"'),
    @('allow', 'feature/m1-demo', 'git checkout main'),
    @('allow', 'main',            'git pull origin main'),
    @('allow', 'feature/m1-demo', 'git push -u origin feature/m1-maintenance'),
    @('allow', 'feature/m1-demo', 'git push origin fix-main-docs'),
    @('allow', 'feature/m1-demo', 'git push'),
    @('allow', 'main',            'git push origin v0.1.0'),
    @('allow', 'feature/m1-demo', 'git switch main; git pull')
)

$failed = 0
foreach ($c in $cases) {
    $expect, $branch, $command = $c
    git -C $repo symbolic-ref HEAD "refs/heads/$branch"
    $json = @{ tool_input = @{ command = $command }; cwd = $repo } | ConvertTo-Json -Compress
    $json | powershell.exe -NoProfile -ExecutionPolicy Bypass -File $guard 2>$null | Out-Null
    $got = if ($LASTEXITCODE -eq 2) { 'block' } else { 'allow' }
    $mark = if ($got -eq $expect) { 'PASS' } else { $failed++; 'FAIL' }
    '{0}  {1,-5} on {2,-16} {3}' -f $mark, $got, $branch, $command
}
Remove-Item -Recurse -Force $repo
"{0} of {1} passed" -f ($cases.Count - $failed), $cases.Count
exit [int]($failed -gt 0)
