param(
    [string]$Config = "configs/dev.yaml",
    [switch]$InstallSqlServerDeps
)

$ErrorActionPreference = "Stop"

function Resolve-PythonCommand {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return [PSCustomObject]@{
            Command = $pythonCmd.Source
            Prefix  = @()
        }
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        foreach ($selector in @("-3.11", "-3")) {
            try {
                & $pyLauncher.Source $selector --version *> $null
                if ($LASTEXITCODE -eq 0) {
                    return [PSCustomObject]@{
                        Command = $pyLauncher.Source
                        Prefix  = @($selector)
                    }
                }
            } catch {
                # Keep trying other selectors.
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
