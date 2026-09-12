<#
.SYNOPSIS
    One-click production frontend build (dist/) — bakes VITE_API_BASE_URL in to point at the
    production backend domain, avoiding the case where manually typing the command and forgetting to
    set the environment variable lets dist/ silently fall back to the default
    http://localhost:8000 (once deployed to production, every request hits port 8000 on the visitor's
    own machine, which looks online like "the frontend loads but every API call 404s/fails to
    connect" — see the "Production build" section of frontend/README.md).

.DESCRIPTION
    This script only does one thing, "build" — it doesn't automatically git add/commit/push; whether
    dist/ needs to be committed, and when, is left to the user's own judgment (the repo convention is
    "changes get committed only after being confirmed," see CLAUDE.md). It prints the next git
    commands to run once the build succeeds — just follow them.

    The default production backend address is https://your-backend-domain.example (a placeholder —
    change it to whatever backend domain you actually deploy to). To build in "same-domain reverse
    proxy" mode (VITE_API_BASE_URL left empty, requests go through the relative path /api/...), just
    override it with the -ApiBaseUrl parameter, no need to change this script itself.

.PARAMETER ApiBaseUrl
    The full backend URL baked into dist. Defaults to https://your-backend-domain.example. Pass an
    empty string (-ApiBaseUrl "") to build in "same-domain reverse proxy" mode, so frontend requests
    go through a relative path.

.EXAMPLE
    .\build-prod.ps1
    Builds with the default production backend address.

.EXAMPLE
    .\build-prod.ps1 -ApiBaseUrl "https://staging-api.example.com"
    Builds pointing at a different backend (e.g. a temporary staging environment for testing).
#>

param(
    [string]$ApiBaseUrl = "https://your-backend-domain.example"
)

$ErrorActionPreference = "Stop"

# The script may be invoked from any working directory (double-clicked, run via a relative path from
# some other directory...) — first locate the frontend/ directory the script itself lives in; every
# npm/git command below is based on that, independent of whether the caller's cwd happens to be
# correct.
Set-Location $PSScriptRoot

Write-Host "== ATBA frontend production build ==" -ForegroundColor Cyan
if ($ApiBaseUrl -eq "") {
    Write-Host "VITE_API_BASE_URL = (empty, same-domain reverse-proxy relative path /api/...)" -ForegroundColor Yellow
} else {
    Write-Host "VITE_API_BASE_URL = $ApiBaseUrl" -ForegroundColor Yellow
}

# package.json's build script is "tsc -b && vite build" — type-checks first; if types don't pass, it
# fails right there, never carrying a type-broken version further to produce a dist/ (see
# package.json).
$env:VITE_API_BASE_URL = $ApiBaseUrl
npm run build
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nBuild failed (npm run build exited with code $LASTEXITCODE), dist/ was not updated." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "`nBuild succeeded, dist/ has been updated." -ForegroundColor Green

# Only a suggestion, not run automatically — whether to commit, and whether to bundle in other
# changes at the same time, is left to the user's own judgment.
$gitStatus = git status --porcelain -- dist 2>$null
if ($gitStatus) {
    Write-Host "`ndist/ has pending changes to commit; once confirmed, you can run:" -ForegroundColor Cyan
    Write-Host "  git add dist" -ForegroundColor Gray
    Write-Host "  git commit -m `"Update frontend production build artifacts`"" -ForegroundColor Gray
    Write-Host "  git push" -ForegroundColor Gray
} else {
    Write-Host "`ndist/ is unchanged since the last commit (either the source didn't change, or it was already built with the same VITE_API_BASE_URL last time)." -ForegroundColor DarkGray
}
