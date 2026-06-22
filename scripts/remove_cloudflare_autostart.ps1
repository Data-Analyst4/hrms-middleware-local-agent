# Remove Cloudflare tunnel autostart (service + watchdog task).
param(
    [string]$ServiceName = "cloudflared",
    [string]$WatchdogTaskName = "V8-Cloudflare-Tunnel-Watchdog"
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdmin)) {
    throw "Run as Administrator."
}

$cloudflaredExe = @(
    "C:\Program Files (x86)\cloudflared\cloudflared.exe",
    "C:\Program Files\cloudflared\cloudflared.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

Unregister-ScheduledTask -TaskName $WatchdogTaskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Removed scheduled task: $WatchdogTaskName" -ForegroundColor Yellow

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc) {
    if ($svc.Status -eq "Running") {
        Stop-Service -Name $ServiceName -Force
    }
    if ($cloudflaredExe) {
        & $cloudflaredExe service uninstall 2>$null | Out-Null
    }
    Write-Host "Removed Windows service: $ServiceName" -ForegroundColor Yellow
}

Write-Host "Done. Manual tunnel: cloudflared tunnel --config `"$env:USERPROFILE\.cloudflared\config-v8-middleware.yml`" run v8-middleware"
