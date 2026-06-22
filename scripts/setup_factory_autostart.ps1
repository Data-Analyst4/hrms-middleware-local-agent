# One-shot factory autostart: middleware + Cloudflare tunnel on boot and after crashes.
# Run as Administrator:
#   .\scripts\setup_factory_autostart.ps1 -StartNow
# Or double-click: SETUP_FACTORY_AUTOSTART.cmd

param(
    [string]$Config = "configs/factory.yaml",
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdmin)) {
    throw "Run as Administrator. Easiest: double-click SETUP_FACTORY_AUTOSTART.cmd in the HR Module folder."
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " V8 Factory autostart setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/2] Middleware supervisor (gateway, FK, worker, device pull)..." -ForegroundColor Yellow
& (Join-Path $PSScriptRoot "setup_autostart.ps1") -Config $Config -StartNow:$StartNow

Write-Host ""
Write-Host "[2/2] Cloudflare tunnel (v8-mw.k95foods.com)..." -ForegroundColor Yellow
& (Join-Path $PSScriptRoot "setup_cloudflare_autostart.ps1") -StartNow:$StartNow

Write-Host ""
Write-Host "Waiting 15s for services to come up..." -ForegroundColor Gray
Start-Sleep -Seconds 15

$okLocal = $false
$okTunnel = $false
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8080/health" -UseBasicParsing -TimeoutSec 10
    $okLocal = ($r.StatusCode -eq 200)
} catch { }

try {
    $r = Invoke-WebRequest -Uri "https://v8-mw.k95foods.com/health" -UseBasicParsing -TimeoutSec 25
    $okTunnel = ($r.StatusCode -eq 200)
} catch { }

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Verification" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Get-ScheduledTask -TaskName "HRMS-Middleware-Supervisor","V8-Cloudflare-Tunnel-Watchdog" -ErrorAction SilentlyContinue |
    Format-Table TaskName, State -AutoSize
Get-Service cloudflared -ErrorAction SilentlyContinue | Format-Table Name, Status, StartType -AutoSize
Write-Host "Local middleware  : $(if ($okLocal) { 'OK' } else { 'FAIL - check var\logs\supervisor.log' })" -ForegroundColor $(if ($okLocal) { 'Green' } else { 'Red' })
Write-Host "Public tunnel     : $(if ($okTunnel) { 'OK' } else { 'FAIL - check var\logs\cloudflared-watchdog.log' })" -ForegroundColor $(if ($okTunnel) { 'Green' } else { 'Red' })
Write-Host ""
Write-Host "After every reboot, both should start automatically within ~1 minute." -ForegroundColor Green
Write-Host "Logs: var\logs\supervisor.log  var\logs\cloudflared-watchdog.log" -ForegroundColor Gray
