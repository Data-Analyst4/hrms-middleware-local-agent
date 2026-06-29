# LAN static IP + firewall + device live-push target (reads IP from site.local.yaml).
param(
    [int]$Port = 8081,
    [string]$DeviceIp = "",
    [string]$Config = "configs/factory.yaml",
    [switch]$SkipLanStatic
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib\project_paths.ps1")

$projectRoot = Get-ProjectRoot -ScriptRoot $PSScriptRoot
if (-not $DeviceIp) {
    $DeviceIp = Read-SiteYamlValue -Key "device_lan_ip_for_firewall" -ProjectRoot $projectRoot
}
if (-not $DeviceIp) {
    $DeviceIp = Read-SiteYamlValue -Key "machine_sync_ip" -ProjectRoot $projectRoot
}
if (-not $DeviceIp) {
    throw "Set machine_sync_ip in configs\site.local.yaml"
}

if (-not (Test-IsAdmin)) {
    throw "Run as Administrator."
}

if (-not $SkipLanStatic) {
    Write-Host ""
    Write-Host "Step 1/2: Lock middleware PC LAN IP (Windows static IP)..." -ForegroundColor Cyan
    $lanScript = Join-Path $PSScriptRoot "configure_lan_static_ip.ps1"
    if (-not (Get-Command Set-AdapterStaticIp -ErrorAction SilentlyContinue)) {
        . (Join-Path $PSScriptRoot "lib\lan_network.ps1")
    }
    & $lanScript -SkipIfAlreadyStatic
    if ($LASTEXITCODE -gt 1) {
        throw "LAN static IP setup failed. Fix network connectivity, then re-run 3-CONFIGURE_DEVICE.cmd"
    }
    Write-Host ""
    Write-Host "Step 2/2: Firewall + device live-push..." -ForegroundColor Cyan
}

$ruleNames = @("HR Module FK Web 8081", "HRMS-FK-Web-Listener-8081")
foreach ($name in $ruleNames) {
    netsh advfirewall firewall delete rule name="$name" 2>$null | Out-Null
}

netsh advfirewall firewall add rule `
    name="HR Module FK Web 8081" `
    dir=in action=allow protocol=TCP localport=$Port remoteip=$DeviceIp profile=any enable=yes | Out-Null

Write-Host "Firewall: allow TCP $Port from $DeviceIp on all profiles." -ForegroundColor Green

$pythonExe = Get-VenvPython -ProjectRoot $projectRoot
if (Test-Path $pythonExe) {
    Write-Host "Configuring device live-push target..." -ForegroundColor Cyan
    & $pythonExe "scripts\configure_device_live_push.py" "--config" $Config
} else {
    Write-Host "Venv not found. Run 2-INSTALL_FACTORY.cmd first." -ForegroundColor Yellow
}
