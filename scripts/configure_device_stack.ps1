# Firewall + device live-push target (reads IP from site.local.yaml).
param(
    [int]$Port = 8081,
    [string]$DeviceIp = "",
    [string]$Config = "configs/factory.yaml"
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
