# Start all V8 middleware services (gateway + FK listener + worker + device sync).
param(
    [string]$Config = "configs/dev.yaml"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}

function Start-IfNotRunning {
    param(
        [string]$Name,
        [string]$Match,
        [string[]]$ProcessArgs
    )
    $existing = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$Match*" }
    if ($existing) {
        Write-Host "$Name already running (pid=$($existing[0].ProcessId))" -ForegroundColor Yellow
        return
    }
    $proc = Start-Process -FilePath $pythonExe -ArgumentList $ProcessArgs -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
    Write-Host "Started $Name pid=$($proc.Id)" -ForegroundColor Green
}

Start-IfNotRunning -Name "gateway" -Match "run_gateway.py" -ProcessArgs @("scripts/run_gateway.py", "--config", $Config)
Start-IfNotRunning -Name "fk-listener" -Match "run_fk_web_listener.py" -ProcessArgs @("scripts/run_fk_web_listener.py", "--config", $Config)
Start-IfNotRunning -Name "worker" -Match "run_worker.py" -ProcessArgs @("scripts/run_worker.py", "--config", $Config)
Start-IfNotRunning -Name "device-sync" -Match "run_device_sync_loop.py" -ProcessArgs @("scripts/run_device_sync_loop.py", "--config", $Config, "--interval", "30")

Write-Host ""
Write-Host "V8 stack started. Punch on T501 -> site PC -> dev.erp.k95foods.com within ~30-45 seconds." -ForegroundColor Cyan
Write-Host "ERP UI: https://dev.erp.k95foods.com/HRAttendanceLogs (clear date filter, use 16/06/2026)" -ForegroundColor Cyan
Write-Host "For instant live push, run scripts/fix_live_push_firewall.ps1 as Administrator." -ForegroundColor Cyan
