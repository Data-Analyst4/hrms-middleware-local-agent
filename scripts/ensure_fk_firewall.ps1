# Allow T501 live punch HTTP push to FK listener (port 8081) from the device LAN.
param(
    [int]$Port = 8081,
    [string]$DeviceIp = "192.168.29.44",
    [string]$RuleName = "HRMS-FK-Web-Listener-8081"
)

$ErrorActionPreference = "Stop"

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Re-run as Administrator to create firewall rule." -ForegroundColor Yellow
    exit 1
}

$existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
if ($existing) {
    Remove-NetFirewallRule -DisplayName $RuleName
}

New-NetFirewallRule `
    -DisplayName $RuleName `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $Port `
    -RemoteAddress $DeviceIp `
    -Profile Any | Out-Null

Write-Host "Firewall rule '$RuleName' allows TCP $Port from $DeviceIp" -ForegroundColor Green
