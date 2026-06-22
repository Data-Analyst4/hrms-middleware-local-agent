param(
    [string]$TaskName = "HRMS-Middleware-Supervisor",
    [switch]$KeepAutoStart
)

$ErrorActionPreference = "Continue"

Write-Host "== Stopping HRMS Middleware Stack ==" -ForegroundColor Cyan

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    if ($task.State -eq "Running") {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Write-Host "Stopped scheduled task: $TaskName" -ForegroundColor Green
    }

    if (-not $KeepAutoStart) {
        Write-Host "Auto-start task kept registered (will start again on reboot)." -ForegroundColor Yellow
        Write-Host "To remove boot auto-start: .\scripts\remove_autostart.ps1" -ForegroundColor Gray
    }
}

$patterns = @("run_stack_forever.ps1", "run_gateway.py", "run_worker.py", "run_fk_web_listener.py", "run_webhook_dispatch.py", "pull_device_logs_to_db.py")
$stopped = 0

foreach ($pattern in $patterns) {
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$pattern*" }

    foreach ($proc in $procs) {
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
            Write-Host "Stopped pid=$($proc.ProcessId) ($pattern)" -ForegroundColor Green
            $stopped++
        } catch {
            Write-Warning "Could not stop pid=$($proc.ProcessId): $($_.Exception.Message)"
        }
    }
}

if ($stopped -eq 0) {
    Write-Host "No middleware processes were running." -ForegroundColor Yellow
} else {
    Write-Host "Stopped $stopped process(es)." -ForegroundColor Green
}
