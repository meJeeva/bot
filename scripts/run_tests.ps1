<#
.SYNOPSIS
    Runs the automated tests.

.DESCRIPTION
    Runs the backend pytest suite and the frontend vitest suite and reports a
    combined result. Exit code is 0 only when every suite passes.

    By default the genuine MetaTrader 5 integration tests are SKIPPED, because
    they need a running, authenticated terminal. Pass -IncludeLive to run them,
    or -LiveOnly to run nothing else.

    Run from the project root:
        powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1
        powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1 -IncludeLive

.PARAMETER IncludeLive
    Also run the live MetaTrader 5 integration tests (marked "live").

.PARAMETER LiveOnly
    Run only the live MetaTrader 5 integration tests.

.PARAMETER BackendOnly
    Skip the frontend suite.

.PARAMETER FrontendOnly
    Skip the backend suite.
#>
[CmdletBinding()]
param(
    [switch]$IncludeLive,
    [switch]$LiveOnly,
    [switch]$BackendOnly,
    [switch]$FrontendOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BackendDir  = Join-Path $ProjectRoot 'backend'
$FrontendDir = Join-Path $ProjectRoot 'frontend'
$VenvPython  = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

$results = [ordered]@{}
$failed = $false

function Write-Step { param([string]$Message) Write-Host "`n==> $Message" -ForegroundColor Cyan }

if (-not (Test-Path $VenvPython)) {
    Write-Host "`n[ERROR] The virtual environment is missing: $VenvPython" -ForegroundColor Red
    Write-Host '        Run .\scripts\setup_windows.ps1 first.' -ForegroundColor Yellow
    exit 1
}

$runBackend = -not $FrontendOnly
$runFrontend = -not $BackendOnly -and -not $LiveOnly

# ---------------------------------------------------------------------------
if ($runBackend) {
    if ($LiveOnly) {
        Write-Step 'Backend: MetaTrader 5 integration tests (LIVE)'
        $selection = @('-m', 'live')
    } elseif ($IncludeLive) {
        Write-Step 'Backend: full suite including live MT5 integration tests'
        $selection = @()
    } else {
        Write-Step 'Backend: mock-based suite (live MT5 tests deselected)'
        $selection = @('-m', 'not live')
    }

    Push-Location $BackendDir
    try {
        & $VenvPython -m pytest @selection
        $backendExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }

    if ($backendExit -eq 0) {
        $results['backend pytest'] = 'PASSED'
    } else {
        $results['backend pytest'] = "FAILED (exit $backendExit)"
        $failed = $true
    }
}

# ---------------------------------------------------------------------------
if ($runFrontend) {
    Write-Step 'Frontend: vitest suite'

    if (-not (Test-Path (Join-Path $FrontendDir 'node_modules'))) {
        $results['frontend vitest'] = 'SKIPPED (dependencies not installed)'
        Write-Host '    frontend\node_modules is missing; run .\scripts\setup_windows.ps1' -ForegroundColor Yellow
    } else {
        Push-Location $FrontendDir
        try {
            & npm run test
            $frontendExit = $LASTEXITCODE
        } finally {
            Pop-Location
        }

        if ($frontendExit -eq 0) {
            $results['frontend vitest'] = 'PASSED'
        } else {
            $results['frontend vitest'] = "FAILED (exit $frontendExit)"
            $failed = $true
        }
    }
}

# ---------------------------------------------------------------------------
Write-Host ''
Write-Host '=============================================' -ForegroundColor White
Write-Host ' Test summary' -ForegroundColor White
Write-Host '=============================================' -ForegroundColor White
foreach ($entry in $results.GetEnumerator()) {
    $colour = if ($entry.Value -like 'PASSED*') { 'Green' } elseif ($entry.Value -like 'SKIPPED*') { 'Yellow' } else { 'Red' }
    Write-Host ("  {0,-18} {1}" -f $entry.Key, $entry.Value) -ForegroundColor $colour
}

if (-not $IncludeLive -and -not $LiveOnly) {
    Write-Host ''
    Write-Host '  Note: live MetaTrader 5 integration tests were deselected.' -ForegroundColor DarkGray
    Write-Host '        Run with -IncludeLive (a terminal must be running and logged in).' -ForegroundColor DarkGray
}

if ($failed) {
    Write-Host "`nOne or more suites failed." -ForegroundColor Red
    exit 1
}

Write-Host "`nAll selected suites passed." -ForegroundColor Green
exit 0
