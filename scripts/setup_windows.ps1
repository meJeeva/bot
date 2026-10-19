<#
.SYNOPSIS
    Prepares the Phase 1 development environment on Windows.

.DESCRIPTION
    Verifies the Python and Node toolchains, creates the Python virtual
    environment, installs backend and frontend dependencies, verifies the
    MetaTrader 5 integration, and seeds the local .env files.

    Run it from the project root:
        powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1

.PARAMETER Recreate
    Delete and rebuild the virtual environment from scratch.

.PARAMETER SkipFrontend
    Do not install frontend dependencies.

.PARAMETER SkipBackend
    Do not install backend dependencies.
#>
[CmdletBinding()]
param(
    [switch]$Recreate,
    [switch]$SkipFrontend,
    [switch]$SkipBackend
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectRoot  = Split-Path -Parent $PSScriptRoot
$BackendDir   = Join-Path $ProjectRoot 'backend'
$FrontendDir  = Join-Path $ProjectRoot 'frontend'
$VenvDir      = Join-Path $ProjectRoot '.venv'
$VenvPython   = Join-Path $VenvDir 'Scripts\python.exe'

$RequiredPython = [version]'3.10'
$RequiredNode   = [version]'18.0'

function Write-Step { param([string]$Message) Write-Host "`n==> $Message" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Message) Write-Host "    [ok]   $Message" -ForegroundColor Green }
function Write-Note { param([string]$Message) Write-Host "    [note] $Message" -ForegroundColor DarkGray }
function Write-Warn { param([string]$Message) Write-Host "    [warn] $Message" -ForegroundColor Yellow }

function Stop-WithError {
    param([string]$Message, [string]$Remedy)
    Write-Host "`n[ERROR] $Message" -ForegroundColor Red
    if ($Remedy) { Write-Host "        $Remedy" -ForegroundColor Yellow }
    exit 1
}

function Get-ToolVersion {
    param([string]$Command, [string[]]$Arguments)
    try {
        $raw = & $Command @Arguments 2>&1 | Select-Object -First 1
        if ($null -eq $raw) { return $null }
        $text = ([string]$raw).Trim() -replace '^v', ''
        if ($text -match '^(\d+\.\d+(\.\d+)?)') { return [version]$Matches[1] }
        return $null
    } catch {
        return $null
    }
}

Write-Host 'Fibonacci MT5 Bot - Phase 1 Windows setup' -ForegroundColor White
Write-Host "Project root: $ProjectRoot"

# ---------------------------------------------------------------------------
Write-Step 'Checking Python'
# ---------------------------------------------------------------------------
$pythonCmd = $null
foreach ($candidate in @('python', 'py')) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $version = Get-ToolVersion -Command $candidate -Arguments @('--version')
        if ($version -and $version -ge $RequiredPython) {
            $pythonCmd = $candidate
            Write-Ok "$candidate $version"
            break
        }
        if ($version) {
            Write-Warn "$candidate is $version; $RequiredPython or newer is required"
        }
    }
}

if (-not $pythonCmd) {
    Stop-WithError `
        "Python $RequiredPython or newer was not found on PATH." `
        'Install it from https://www.python.org/downloads/windows/ (tick "Add python.exe to PATH") and reopen the terminal.'
}

# ---------------------------------------------------------------------------
Write-Step 'Checking Node.js and npm'
# ---------------------------------------------------------------------------
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Stop-WithError 'Node.js was not found on PATH.' 'Install the LTS release from https://nodejs.org/ and reopen the terminal.'
}
$nodeVersion = Get-ToolVersion -Command 'node' -Arguments @('--version')
if (-not $nodeVersion -or $nodeVersion -lt $RequiredNode) {
    Stop-WithError "Node.js $RequiredNode or newer is required (found $nodeVersion)." 'Install the LTS release from https://nodejs.org/.'
}
Write-Ok "node $nodeVersion"

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Stop-WithError 'npm was not found on PATH.' 'npm ships with Node.js; reinstall Node.js if it is missing.'
}
Write-Ok "npm $(Get-ToolVersion -Command 'npm' -Arguments @('-v'))"

# ---------------------------------------------------------------------------
Write-Step 'Checking the MetaTrader 5 desktop terminal'
# ---------------------------------------------------------------------------
$terminalCandidates = @()
if ($env:APPDATA) {
    $instances = Join-Path $env:APPDATA 'MetaQuotes\Terminal'
    if (Test-Path $instances) {
        Get-ChildItem -Path $instances -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            $origin = Join-Path $_.FullName 'origin.txt'
            if (Test-Path $origin) {
                try {
                    $installDir = (Get-Content -Path $origin -Raw -Encoding Unicode).Trim()
                    $exe = Join-Path $installDir 'terminal64.exe'
                    if (Test-Path $exe) { $terminalCandidates += $exe }
                } catch { }
            }
        }
    }
}
foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
    if ($root) {
        $exe = Join-Path $root 'MetaTrader 5\terminal64.exe'
        if (Test-Path $exe) { $terminalCandidates += $exe }
    }
}
$terminalCandidates = $terminalCandidates | Sort-Object -Unique

if ($terminalCandidates.Count -eq 0) {
    Write-Warn 'No MetaTrader 5 terminal was found. The backend will start but will report a disconnected terminal.'
    Write-Note 'Install the terminal from your broker and log it into a demo account before expecting live data.'
} else {
    foreach ($candidate in $terminalCandidates) { Write-Ok "terminal: $candidate" }
    Write-Note 'The backend discovers these automatically; set MT5_TERMINAL_PATH in backend\.env to pin one.'
}

# ---------------------------------------------------------------------------
if (-not $SkipBackend) {
    Write-Step 'Creating the Python virtual environment'
    if ($Recreate -and (Test-Path $VenvDir)) {
        Write-Note "removing $VenvDir"
        Remove-Item -Recurse -Force $VenvDir
    }

    if (-not (Test-Path $VenvPython)) {
        & $pythonCmd -m venv $VenvDir
        if ($LASTEXITCODE -ne 0) {
            Stop-WithError 'python -m venv failed.' 'Check that the "venv" module is available in your Python installation.'
        }
        Write-Ok "created $VenvDir"
    } else {
        Write-Ok "reusing $VenvDir"
    }

    Write-Step 'Installing backend dependencies'
    & $VenvPython -m pip install --upgrade pip --quiet
    if ($LASTEXITCODE -ne 0) { Stop-WithError 'pip upgrade failed.' 'Check your network connection and proxy settings.' }

    $requirements = Join-Path $BackendDir 'requirements.txt'
    & $VenvPython -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "pip install -r $requirements failed." 'Read the pip output above; it names the failing package.'
    }
    Write-Ok 'backend dependencies installed'

    Write-Step 'Verifying the MetaTrader5 Python package'
    & $VenvPython -c "import MetaTrader5 as mt5; print('MetaTrader5', mt5.__version__)"
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError 'The MetaTrader5 package could not be imported.' 'It is Windows-only; ensure you are on Windows and rerun this script.'
    }
    Write-Ok 'MetaTrader5 package importable'

    Write-Step 'Seeding backend\.env'
    $envFile = Join-Path $BackendDir '.env'
    $envExample = Join-Path $BackendDir '.env.example'
    if (Test-Path $envFile) {
        Write-Ok 'backend\.env already exists (left untouched)'
    } elseif (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-Ok 'created backend\.env from .env.example'
    } else {
        Write-Warn 'backend\.env.example is missing; no .env was created'
    }
}

# ---------------------------------------------------------------------------
if (-not $SkipFrontend) {
    Write-Step 'Installing frontend dependencies'
    if (-not (Test-Path $FrontendDir)) {
        Stop-WithError "The frontend directory is missing: $FrontendDir" 'Restore the repository contents.'
    }

    Push-Location $FrontendDir
    try {
        & npm install --no-fund --no-audit
        if ($LASTEXITCODE -ne 0) {
            Stop-WithError 'npm install failed.' 'Read the npm output above; delete frontend\node_modules and retry if it looks corrupted.'
        }
        Write-Ok 'frontend dependencies installed'
    } finally {
        Pop-Location
    }

    $frontendEnv = Join-Path $FrontendDir '.env'
    $frontendExample = Join-Path $FrontendDir '.env.example'
    if (-not (Test-Path $frontendEnv) -and (Test-Path $frontendExample)) {
        Copy-Item $frontendExample $frontendEnv
        Write-Ok 'created frontend\.env from .env.example'
    }
}

# ---------------------------------------------------------------------------
Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host @'

Next steps
----------
1. Start the MetaTrader 5 terminal and log it into a demo account.
2. Open a second PowerShell window and run:
       .\scripts\start_backend.ps1
3. Open a third PowerShell window and run:
       .\scripts\start_frontend.ps1
4. Open http://localhost:5173 in a browser.
5. Run the automated tests with:
       .\scripts\run_tests.ps1
   and the genuine MT5 integration tests with:
       .\scripts\run_tests.ps1 -IncludeLive

If PowerShell blocks the scripts, run them as:
    powershell -ExecutionPolicy Bypass -File .\scripts\<name>.ps1
'@ -ForegroundColor Gray
