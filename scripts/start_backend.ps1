<#
.SYNOPSIS
    Starts the read-only FastAPI backend against the local MetaTrader 5 terminal.

.DESCRIPTION
    Activates the project virtual environment and runs uvicorn. Host and port
    are taken from backend\.env when present. The process keeps running until
    you press Ctrl+C, which triggers a clean MT5 shutdown.

    Run it from the project root:
        powershell -ExecutionPolicy Bypass -File .\scripts\start_backend.ps1

.PARAMETER Host
    Override the bind address (default: BACKEND_HOST from .env, else 127.0.0.1).

.PARAMETER Port
    Override the port (default: BACKEND_PORT from .env, else 8000).

.PARAMETER NoReload
    Disable uvicorn's auto-reload. Use this for long monitoring sessions, since
    a reload restarts the MT5 connection.
#>
[CmdletBinding()]
param(
    [string]$BindHost,
    [int]$Port,
    [switch]$NoReload
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BackendDir  = Join-Path $ProjectRoot 'backend'
$VenvPython  = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$EnvFile     = Join-Path $BackendDir '.env'

function Stop-WithError {
    param([string]$Message, [string]$Remedy)
    Write-Host "`n[ERROR] $Message" -ForegroundColor Red
    if ($Remedy) { Write-Host "        $Remedy" -ForegroundColor Yellow }
    exit 1
}

function Get-EnvFileValue {
    param([string]$Path, [string]$Key, [string]$Default)
    if (-not (Test-Path $Path)) { return $Default }
    foreach ($line in Get-Content -Path $Path) {
        $trimmed = $line.Trim()
        if ($trimmed -eq '' -or $trimmed.StartsWith('#')) { continue }
        if ($trimmed -match "^\s*$([regex]::Escape($Key))\s*=\s*(.*)$") {
            $value = $Matches[1].Trim().Trim('"').Trim("'")
            if ($value -ne '') { return $value }
        }
    }
    return $Default
}

if (-not (Test-Path $VenvPython)) {
    Stop-WithError "The virtual environment is missing: $VenvPython" 'Run .\scripts\setup_windows.ps1 first.'
}

if (-not (Test-Path $BackendDir)) {
    Stop-WithError "The backend directory is missing: $BackendDir" 'Restore the repository contents.'
}

if (-not $BindHost) {
    $BindHost = Get-EnvFileValue -Path $EnvFile -Key 'BACKEND_HOST' -Default '127.0.0.1'
}
if (-not $Port -or $Port -le 0) {
    $configuredPort = Get-EnvFileValue -Path $EnvFile -Key 'BACKEND_PORT' -Default '8000'
    $Port = [int]$configuredPort
}

Write-Host 'MT5 Market Data - backend' -ForegroundColor White
Write-Host "  python : $VenvPython"
Write-Host "  bind   : http://${BindHost}:$Port"
Write-Host "  api    : http://${BindHost}:$Port/docs"
Write-Host ''
Write-Host 'The MetaTrader 5 desktop terminal must be running and logged in for live data.' -ForegroundColor DarkGray
Write-Host 'Press Ctrl+C to stop the backend (this shuts the MT5 connection down cleanly).' -ForegroundColor DarkGray
Write-Host ''

$uvicornArgs = @(
    '-m', 'uvicorn', '--factory', 'app.main:create_app',
    '--host', $BindHost,
    '--port', "$Port"
)
if (-not $NoReload) {
    $uvicornArgs += '--reload'
}

Push-Location $BackendDir
try {
    & $VenvPython @uvicornArgs
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($exitCode -ne 0) {
    Stop-WithError "uvicorn exited with code $exitCode." 'Read the traceback above; a configuration error is reported with the exact field name.'
}

Write-Host 'Backend stopped.' -ForegroundColor Green
