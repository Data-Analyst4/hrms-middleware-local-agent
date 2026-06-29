param(
    [string]$Config = "configs/dev.yaml",
    [switch]$InstallSqlServerDeps
)

$ErrorActionPreference = "Stop"

function Refresh-SessionPath {
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Test-PythonExecutable {
    param(
        [string]$Command,
        [string[]]$Prefix = @()
    )
    if (-not $Command -or -not (Test-Path $Command)) {
        if ($Command -notmatch '\\') {
            $resolved = Get-Command $Command -ErrorAction SilentlyContinue
            if (-not $resolved) { return $false }
            $Command = $resolved.Source
        } else {
            return $false
        }
    }
    if ($Command -like "*\WindowsApps\*") { return $false }
    try {
        $args = @()
        $args += $Prefix
        $args += @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")
        & $Command @args 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Resolve-PythonCommand {
    Refresh-SessionPath

    $candidates = @()

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $candidates += @{ Command = $pyLauncher.Source; Prefix = @("-3.11") }
        $candidates += @{ Command = $pyLauncher.Source; Prefix = @("-3") }
    }

    foreach ($installPath in @(
        "$env:LocalAppData\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python311\python.exe",
        "${env:ProgramFiles(x86)}\Python311\python.exe"
    )) {
        if (Test-Path $installPath) {
            $candidates += @{ Command = $installPath; Prefix = @() }
        }
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd -and $pythonCmd.Source -notlike "*\WindowsApps\*") {
        $candidates += @{ Command = $pythonCmd.Source; Prefix = @() }
    }

    foreach ($candidate in $candidates) {
        if (Test-PythonExecutable -Command $candidate.Command -Prefix $candidate.Prefix) {
            return [PSCustomObject]@{
                Command = $candidate.Command
                Prefix  = $candidate.Prefix
            }
        }
    }

    return $null
}

Write-Host "== HRMS Middleware Local Installer ==" -ForegroundColor Cyan
Write-Host "Project: $PSScriptRoot\.."

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

$python = Resolve-PythonCommand
if (-not $python) {
    throw "Python 3.11+ is not installed or not discoverable. Install Python and retry."
}

$versionArgs = @()
$versionArgs += $python.Prefix
$versionArgs += "--version"
& $python.Command @versionArgs

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    $venvArgs = @()
    $venvArgs += $python.Prefix
    $venvArgs += @("-m", "venv", ".venv")
    & $python.Command @venvArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create virtual environment. Close this window, open a new Administrator cmd, run: py -3.11 --version then re-run 2-INSTALL_FACTORY.cmd"
    }
}

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Virtual environment python not found: $pythonExe"
}

Write-Host "Installing dependencies..."
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install -r requirements.txt
& $pythonExe -m pip install -e .

if ($InstallSqlServerDeps) {
    Write-Host "Installing SQL Server optional dependencies..."
    & $pythonExe -m pip install pyodbc
}

Write-Host ""
Write-Host "Installation completed." -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "1) Edit $Config and set API keys / URLs."
Write-Host "2) Start gateway:    .\.venv\Scripts\python.exe scripts\run_gateway.py --config $Config"
Write-Host "3) Start worker:     .\.venv\Scripts\python.exe scripts\run_worker.py --config $Config"
Write-Host "4) Optional webhook: .\.venv\Scripts\python.exe scripts\run_webhook_dispatch.py --config $Config"
