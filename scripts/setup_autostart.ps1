param(
    [string]$Config = "configs/factory.yaml",
    [string]$TaskName = "HRMS-Middleware-Supervisor",
    [int]$BootDelaySeconds = 30,
    [int]$StartupDelaySeconds = 20,
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdmin)) {
    throw "Run this script as Administrator to create boot-start scheduled task."
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$supervisorScript = Join-Path $projectRoot "scripts\run_stack_forever.ps1"
if (-not (Test-Path $supervisorScript)) {
    throw "Supervisor script not found: $supervisorScript"
}

$configAbs = (Resolve-Path (Join-Path $projectRoot $Config)).Path
$logDir = Join-Path $projectRoot "var\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$argLine = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$supervisorScript`" -Config `"$configAbs`" -StartupDelaySeconds $StartupDelaySeconds"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argLine -WorkingDirectory $projectRoot

$trigger = New-ScheduledTaskTrigger -AtStartup
if ($BootDelaySeconds -gt 0) {
    $trigger.Delay = "PT${BootDelaySeconds}S"
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "HRMS middleware supervisor (gateway + worker + webhook dispatcher). Auto-starts on boot and restarts crashed processes." `
    -Force | Out-Null

Write-Host "Scheduled task created: $TaskName" -ForegroundColor Green
Write-Host "  Boot trigger: At system startup (+${BootDelaySeconds}s delay)" -ForegroundColor Gray
Write-Host "  Supervisor log: $logDir\supervisor.log" -ForegroundColor Gray
Write-Host "  Task auto-restarts the supervisor if it crashes." -ForegroundColor Gray

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Task started now: $TaskName" -ForegroundColor Green
}

Write-Host ""
Write-Host "For Cloudflare tunnel autostart (v8-mw.k95foods.com), this is included in INSTALL_ONE_CLICK.cmd." -ForegroundColor Cyan
Write-Host "Re-apply only: .\SETUP_FACTORY_AUTOSTART.cmd" -ForegroundColor Cyan
