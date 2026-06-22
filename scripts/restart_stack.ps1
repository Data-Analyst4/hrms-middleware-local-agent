param(
    [string]$Config = "configs/dev.yaml",
    [string]$TaskName = "HRMS-Middleware-Supervisor"
)

$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "stop_stack.ps1") -TaskName $TaskName
Start-Sleep -Seconds 3

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Restarted via scheduled task: $TaskName" -ForegroundColor Green
} else {
    $projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    $supervisor = Join-Path $projectRoot "scripts\run_stack_forever.ps1"
    Start-Process powershell.exe `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", "`"$supervisor`"", "-Config", "`"$Config`"") `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden | Out-Null
    Write-Host "Started supervisor manually (no scheduled task found)." -ForegroundColor Yellow
}

Start-Sleep -Seconds 5
& (Join-Path $PSScriptRoot "check_stack_status.ps1") -Config $Config -TaskName $TaskName
