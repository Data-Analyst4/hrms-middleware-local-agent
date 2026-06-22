# Start cloudflared tunnel process now (no Windows service required).
param(
    [string]$ConfigPath = "C:\ProgramData\cloudflared\config.yml",
    [string]$TunnelName = "v8-middleware",
    [string]$PublicHostname = "v8-mw.k95foods.com"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib\project_paths.ps1")

$projectRoot = Get-ProjectRoot -ScriptRoot $PSScriptRoot
$hostname = Read-SiteYamlValue -Key "cloudflare_public_hostname" -Default $PublicHostname -ProjectRoot $projectRoot
$hostname = $hostname -replace '^https?://', '' -replace '/.*$', ''
$tunnelName = Read-SiteYamlValue -Key "cloudflare_tunnel_name" -Default $TunnelName -ProjectRoot $projectRoot

if (-not (Test-Path $ConfigPath)) {
    throw "Missing $ConfigPath - run SETUP_FACTORY_AUTOSTART.cmd or INSTALL_ONE_CLICK.cmd first."
}

$exe = (Get-Command "C:\Program Files (x86)\cloudflared\cloudflared.exe" -ErrorAction SilentlyContinue).Source
if (-not $exe) {
    $exe = (Get-Command cloudflared.exe -ErrorAction SilentlyContinue).Source
}
if (-not $exe) {
    throw "cloudflared.exe not found. Install via winget or INSTALL_ONE_CLICK.cmd."
}

# Local gateway must be up first.
try {
    $local = Invoke-WebRequest -Uri "http://127.0.0.1:8080/health" -UseBasicParsing -TimeoutSec 5
    if ($local.StatusCode -ne 200) {
        throw "Local middleware not healthy on :8080"
    }
} catch {
    throw "Start middleware first (CHECK_STATUS or run_stack_forever). Local :8080 not reachable."
}

Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$logDir = Join-Path $projectRoot "var\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$outLog = Join-Path $logDir "cloudflared-runner.out.log"
$errLog = Join-Path $logDir "cloudflared-runner.err.log"

Write-Host "Starting cloudflared tunnel '$tunnelName'..." -ForegroundColor Cyan
Write-Host "  Config: $ConfigPath"
Write-Host "  Public: https://$hostname/health"

$proc = Start-Process -FilePath $exe `
    -ArgumentList @("tunnel", "--config", $ConfigPath, "run", $tunnelName) `
    -WindowStyle Hidden `
    -PassThru `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog

Start-Sleep -Seconds 8

if ($proc.HasExited) {
    $errTail = ""
    if (Test-Path $errLog) { $errTail = (Get-Content $errLog -Tail 15 -ErrorAction SilentlyContinue) -join "`n" }
    throw "cloudflared exited immediately (code $($proc.ExitCode)). Log:`n$errTail"
}

Set-Content -Path (Join-Path $logDir "cloudflared-mode.txt") -Value "runner" -Encoding ASCII

try {
    $pub = Invoke-WebRequest -Uri "https://$hostname/health" -UseBasicParsing -TimeoutSec 25
    Write-Host "Public tunnel OK: HTTP $($pub.StatusCode)" -ForegroundColor Green
} catch {
    Write-Warning "Tunnel process started (pid=$($proc.Id)) but public health not OK yet: $($_.Exception.Message)"
    Write-Host "Wait 30s and run: curl.exe https://$hostname/health"
    Write-Host "Logs: $errLog"
}

Write-Host ""
Write-Host "cloudflared pid=$($proc.Id) (stops if process killed or PC reboots)."
Write-Host "For boot autostart without Windows service, run as Admin:"
Write-Host "  .\REPAIR_CLOUDFLARE.cmd"
Write-Host "  or  .\SETUP_FACTORY_AUTOSTART.cmd"
