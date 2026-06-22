# Fix T501 live push: Windows blocks port 8081 when Wi-Fi is "Public" network.
# Run this script once as Administrator (right-click PowerShell -> Run as administrator).
param(
    [int]$Port = 8081,
    [string]$DeviceIp = "192.168.29.44"
)

$ErrorActionPreference = "Stop"

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Run as Administrator." -ForegroundColor Red
    exit 1
}

$ruleNames = @(
    "HR Module FK Web 8081",
    "HRMS-FK-Web-Listener-8081"
)

foreach ($name in $ruleNames) {
    netsh advfirewall firewall delete rule name="$name" | Out-Null
}

netsh advfirewall firewall add rule `
    name="HR Module FK Web 8081" `
    dir=in action=allow protocol=TCP localport=$Port remoteip=$DeviceIp profile=any enable=yes | Out-Null

Write-Host "Firewall: allow TCP $Port from $DeviceIp on all profiles (Public/Private)." -ForegroundColor Green
Get-NetConnectionProfile | Format-Table InterfaceAlias, NetworkCategory -AutoSize
