# One-shot deploy for a NEW factory PC (Windows 10/11).
# - Clears old scheduled tasks / processes (fixes wrong folder paths)
# - Generates site keys + site.local.yaml
# - Installs deps, venv, autostart, tunnel, firewall
# All paths are relative to this folder (%~dp0) — copy anywhere.

param(
    [string]$SiteCode = "",
    [string]$SiteName = "",
    [string]$MachineIp = "",
    [int]$MachineNumber = 0,
    [string]$ErpBaseUrl = "https://dev.erp.k95foods.com",
    [switch]$SkipPrompts,
    [switch]$RegenerateKeys,
    [switch]$SkipConfigure,
    [switch]$NoTunnel
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib\project_paths.ps1")

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Request-AdminSelf {
    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    if ($SiteCode) { $argList += "-SiteCode"; $argList += "`"$SiteCode`"" }
    if ($SiteName) { $argList += "-SiteName"; $argList += "`"$SiteName`"" }
    if ($MachineIp) { $argList += "-MachineIp"; $argList += "`"$MachineIp`"" }
    if ($MachineNumber -gt 0) { $argList += "-MachineNumber"; $argList += $MachineNumber }
    if ($ErpBaseUrl) { $argList += "-ErpBaseUrl"; $argList += "`"$ErpBaseUrl`"" }
    if ($SkipPrompts) { $argList += "-SkipPrompts" }
    if ($RegenerateKeys) { $argList += "-RegenerateKeys" }
    if ($SkipConfigure) { $argList += "-SkipConfigure" }
    if ($NoTunnel) { $argList += "-NoTunnel" }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $argList | Out-Null
    exit 0
}

if (-not (Test-IsAdmin)) {
    Write-Host "Administrator required for install + autostart + firewall." -ForegroundColor Yellow
    Request-AdminSelf
}

$projectRoot = Get-ProjectRoot -ScriptRoot $PSScriptRoot
Set-Location $projectRoot

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " HRMS Middleware — Deploy New Site PC" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Folder:  $projectRoot"
Write-Host "Windows: $([System.Environment]::OSVersion.VersionString)"
Write-Host ""

# --- 1) Stop old stack + remove stale autostart (any previous folder path) ---
Write-Host "[1/5] Stopping old processes and re-registering autostart paths..." -ForegroundColor Yellow
& (Join-Path $projectRoot "scripts\stop_stack.ps1") | Out-Host

foreach ($task in @("HRMS-Middleware-Supervisor", "V8-Cloudflare-Tunnel-Watchdog", "V8-Cloudflare-Tunnel-Runner")) {
    if (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $task -Confirm:$false
        Write-Host "  Removed old task: $task" -ForegroundColor Gray
    }
}

# --- 2) Per-site config + keys ---
if (-not $SkipConfigure) {
    Write-Host ""
    Write-Host "[2/5] Site config + API keys..." -ForegroundColor Yellow
    $configureScript = Join-Path $projectRoot "scripts\configure_site.ps1"
    $configParams = @{}
    if ($SiteCode) { $configParams.SiteCode = $SiteCode }
    if ($SiteName) { $configParams.SiteName = $SiteName }
    if ($MachineIp) { $configParams.MachineIp = $MachineIp }
    if ($MachineNumber -gt 0) { $configParams.MachineNumber = $MachineNumber }
    if ($ErpBaseUrl) { $configParams.ErpBaseUrl = $ErpBaseUrl }
    if ($SkipPrompts) { $configParams.SkipPrompts = $true }
    if ($RegenerateKeys) { $configParams.RegenerateKeys = $true }
    & $configureScript @configParams
} else {
    Write-Host "[2/5] Skipped configure (using existing site.local.yaml)" -ForegroundColor Gray
}

# --- 3) Full install (Python, venv, deps, autostart, tunnel) ---
Write-Host ""
Write-Host "[3/5] Install dependencies + register boot autostart..." -ForegroundColor Yellow
$installArgs = @{
    Config         = "configs/factory.yaml"
    SkipSiteInit   = $true
}
if ($NoTunnel) { $installArgs.NoTunnel = $true }
& (Join-Path $projectRoot "INSTALL_ONE_CLICK.ps1") @installArgs

# --- 4) Live-push firewall for biometric device ---
Write-Host ""
Write-Host "[4/5] Firewall for device live-push (port 8081)..." -ForegroundColor Yellow
$deviceIp = Read-SiteYamlValue -Key "device_lan_ip_for_firewall" -ProjectRoot $projectRoot
if (-not $deviceIp) {
    $deviceIp = Read-SiteYamlValue -Key "machine_sync_ip" -ProjectRoot $projectRoot
}
if ($deviceIp) {
    $fwScript = Join-Path $projectRoot "scripts\fix_live_push_firewall.ps1"
    if (Test-Path $fwScript) {
        & $fwScript -DeviceIp $deviceIp -Port 8081
    }
}

# --- 5) Status check ---
Write-Host ""
Write-Host "[5/5] Health check..." -ForegroundColor Yellow
Start-Sleep -Seconds 10
& (Join-Path $projectRoot "scripts\check_stack_status.ps1") -Config "configs/factory.yaml"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Deploy complete" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Send to K95 DevOps: configs\k95-vps-snippet.env"
Write-Host "Verify punches:     .\.venv\Scripts\python.exe scripts\_probe_erp_punch.py"
Write-Host "Verify tunnel:      curl.exe -s https://$(Read-SiteYamlValue -Key 'cloudflare_public_hostname' -ProjectRoot $projectRoot)/health"
Write-Host ""
Write-Host "Resilience (automatic):" -ForegroundColor Cyan
Write-Host "  ISP/WiFi public IP change  -> Cloudflare tunnel (no action needed)"
Write-Host "  PC LAN IP change           -> SDK pull every 30s + live-push heal every 15 min"
Write-Host "  Process crash              -> supervisor restarts gateway/worker/FK listener"
Write-Host "  PC reboot                  -> scheduled tasks start stack + tunnel"
Write-Host "  ERP punch failure          -> outbox retries + hourly FAILED replay"
Write-Host ""
Write-Host "Recommended: DHCP reservation for this PC + biometric device on router."
Write-Host "Docs: docs\MULTI_SITE_CONFIG.md  docs\PRODUCTION_RESILIENCE.md"
Write-Host ""
