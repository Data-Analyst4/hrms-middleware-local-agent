param(
    [string]$Config = "configs/dev.yaml",
    [switch]$OpenFirewall
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Virtual environment not found. Run scripts/install_local_pc.ps1 first."
}

if ($OpenFirewall) {
    Write-Host "Opening inbound firewall port 8000..."
    try {
        New-NetFirewallRule `
            -DisplayName "HRMS Middleware Gateway 8000" `
            -Direction Inbound `
            -Protocol TCP `
            -Action Allow `
            -LocalPort 8000 `
            -ErrorAction SilentlyContinue | Out-Null
    } catch {
        Write-Warning "Could not create firewall rule automatically. Run as Administrator if needed."
    }
}

Write-Host "Starting gateway on configured host/port..."
& $pythonExe scripts/run_gateway.py --config $Config
