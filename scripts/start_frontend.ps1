<#
.SYNOPSIS
    Starts the Phase 1 React dashboard development server.

.DESCRIPTION
    Runs the Vite dev server, which proxies /api and /ws to the backend so the
    browser sees a single origin. The backend must be started separately with
    .\scripts\start_backend.ps1.

    Run it from the project root:
        powershell -ExecutionPolicy Bypass -File .\scripts\start_frontend.ps1

.PARAMETER Build
    Produce a production build instead of starting the dev server.
#>
[CmdletBinding()]
param(
    [switch]$Build
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $ProjectRoot 'frontend'
$NodeModules = Join-Path $FrontendDir 'node_modules'

function Stop-WithError {
    param([string]$Message, [string]$Remedy)
    Write-Host "`n[ERROR] $Message" -ForegroundColor Red
    if ($Remedy) { Write-Host "        $Remedy" -ForegroundColor Yellow }
    exit 1
}

if (-not (Test-Path $FrontendDir)) {
    Stop-WithError "The frontend directory is missing: $FrontendDir" 'Restore the repository contents.'
}

if (-not (Test-Path $NodeModules)) {
    Stop-WithError "Frontend dependencies are not installed ($NodeModules is missing)." 'Run .\scripts\setup_windows.ps1 first.'
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Stop-WithError 'npm was not found on PATH.' 'Install Node.js LTS from https://nodejs.org/ and reopen the terminal.'
}

Push-Location $FrontendDir
try {
    if ($Build) {
        Write-Host 'Fibonacci MT5 Bot - production build' -ForegroundColor White
        & npm run build
        if ($LASTEXITCODE -ne 0) {
            Stop-WithError 'The production build failed.' 'Read the TypeScript/Vite output above.'
        }
        Write-Host 'Build written to frontend\dist' -ForegroundColor Green
    } else {
        Write-Host 'Fibonacci MT5 Bot - dashboard' -ForegroundColor White
        Write-Host '  url  : http://localhost:5173'
        Write-Host "  proxy: /api and /ws -> the backend configured in vite.config.ts"
        Write-Host ''
        Write-Host 'Start the backend first if you have not already:' -ForegroundColor DarkGray
        Write-Host '    .\scripts\start_backend.ps1' -ForegroundColor DarkGray
        Write-Host ''

        & npm run dev
        if ($LASTEXITCODE -ne 0) {
            Stop-WithError 'The Vite dev server exited with an error.' 'Read the output above; a port conflict on 5173 is the usual cause.'
        }
    }
} finally {
    Pop-Location
}
