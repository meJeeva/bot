<#
.SYNOPSIS
    Runs a reproducible historical Fibonacci backtest for XAUUSD.

.DESCRIPTION
    Loads genuine historical MetaTrader 5 candles through the existing data
    pipeline, re-runs the existing Fibonacci strategy and trade evaluator across
    the seven configured timeframes, and writes CSV + JSON reports under
    reports\backtests\<run-id>\.

    This command is strictly READ-ONLY. It never submits, modifies or closes an
    order, and it never writes to the live strategy store. The MetaTrader 5
    terminal must be running and logged in; a demo account is sufficient.

    Run from the project root:
        powershell -ExecutionPolicy Bypass -File .\scripts\run_backtest.ps1
        powershell -ExecutionPolicy Bypass -File .\scripts\run_backtest.ps1 -Start 2026-04-14 -End 2026-10-14

.PARAMETER Start
    Range start (YYYY-MM-DD or ISO-8601). Default 2026-04-14.

.PARAMETER End
    Range end. A plain date is inclusive of that whole day. Default 2026-10-14.

.PARAMETER Timeframes
    Comma-separated subset of the seven configured timeframes
    (M1,M5,M15,M30,H1,H4,D1). Default: all seven.

.PARAMETER Symbol
    Instrument override. Default: MT5_SYMBOL from backend\.env (XAUUSD).

.PARAMETER OutputDir
    Report directory. Default: reports\backtests.

.PARAMETER SkipTradeEval
    Skip the trade-level evaluator and report confirmation statistics only.

.PARAMETER MaxBarsPerCall
    Historical read chunk size in bars. Default 15000.
#>
[CmdletBinding()]
param(
    [string]$Start = '2026-04-14',
    [string]$End = '2026-10-14',
    [string]$Timeframes = 'M1,M5,M15,M30,H1,H4,D1',
    [string]$Symbol,
    [string]$OutputDir,
    [switch]$SkipTradeEval,
    [int]$MaxBarsPerCall = 15000
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BackendDir  = Join-Path $ProjectRoot 'backend'
$VenvPython  = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $VenvPython)) {
    Write-Host "[ERROR] The virtual environment is missing: $VenvPython" -ForegroundColor Red
    Write-Host '        Run .\scripts\setup_windows.ps1 first.' -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $BackendDir)) {
    Write-Host "[ERROR] The backend directory is missing: $BackendDir" -ForegroundColor Red
    exit 1
}

Write-Host 'Fibonacci MT5 Bot - historical backtest (read-only)' -ForegroundColor White
Write-Host "  python     : $VenvPython"
Write-Host "  range      : $Start .. $End"
Write-Host "  timeframes : $Timeframes"
if ($Symbol) { Write-Host "  symbol     : $Symbol" }
Write-Host ''
Write-Host 'The MetaTrader 5 desktop terminal must be running and logged in.' -ForegroundColor DarkGray
Write-Host 'No order will be placed at any point.' -ForegroundColor DarkGray
Write-Host ''

$cliArgs = @(
    '-m', 'app.backtest.cli',
    '--start', $Start,
    '--end', $End,
    '--timeframes', $Timeframes,
    '--max-bars-per-call', "$MaxBarsPerCall"
)
if ($Symbol)    { $cliArgs += @('--symbol', $Symbol) }
if ($OutputDir) { $cliArgs += @('--output-dir', $OutputDir) }
if ($SkipTradeEval) { $cliArgs += '--skip-trade-eval' }

$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $BackendDir
try {
    Push-Location $BackendDir
    try {
        & $VenvPython @cliArgs
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

if ($exitCode -ne 0) {
    Write-Host "`n[ERROR] The backtest exited with code $exitCode." -ForegroundColor Red
    exit $exitCode
}

Write-Host "`nBacktest completed. Reports were written under:" -ForegroundColor Green
Write-Host "  $(Join-Path $ProjectRoot 'reports\backtests')"
exit 0
