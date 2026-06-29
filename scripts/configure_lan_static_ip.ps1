# Lock middleware PC LAN IP (Windows static IP = Option B).
# Also prints router DHCP reservation info (Option A) - routers cannot be configured from this script.
param(
    [switch]$SkipIfAlreadyStatic,
    [switch]$Force,
    [string]$TargetIp = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib\project_paths.ps1")
. (Join-Path $PSScriptRoot "lib\site_secrets.ps1")
. (Join-Path $PSScriptRoot "lib\lan_network.ps1")

$projectRoot = Get-ProjectRoot -ScriptRoot $PSScriptRoot
$sitePath = Get-SiteLocalConfigPath -ProjectRoot $projectRoot
$logDir = Join-Path $projectRoot "var\lan_setup"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not (Test-IsAdmin)) {
    throw "Run as Administrator (use 3-CONFIGURE_DEVICE.cmd or 4-CONFIGURE_LAN_IP.cmd)."
}

$deviceIp = Read-SiteYamlValue -Key "machine_sync_ip" -ProjectRoot $projectRoot
if (-not $deviceIp) {
    throw "Set machine_sync_ip in configs\site.local.yaml first (run 1-CONFIGURE_SITE.cmd)."
}

$configEnabled = Read-SiteYamlValue -Key "pc_lan_static_enabled" -ProjectRoot $projectRoot -Default "true"
if ($configEnabled -match '^(false|no|0)$' -and -not $Force) {
    Write-Host "pc_lan_static_enabled=false — skipping LAN static IP. Use -Force to override." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "== Configure LAN static IP (middleware PC) ==" -ForegroundColor Cyan
Write-Host "Device on LAN: $deviceIp" -ForegroundColor Gray
Write-Host ""

$choice = Get-LanAdapterForDevice -DeviceIp $deviceIp
$snapshot = Get-AdapterNetworkSnapshot -InterfaceIndex $choice.Address.InterfaceIndex

if (-not $TargetIp) {
    $TargetIp = Read-SiteYamlValue -Key "pc_lan_ip" -ProjectRoot $projectRoot
}
if (-not $TargetIp) {
    $TargetIp = $snapshot.IpAddress
    Write-Host "Locking current DHCP IP as static: $TargetIp" -ForegroundColor Yellow
} else {
    Write-Host "Using target IP from config: $TargetIp" -ForegroundColor Yellow
}

$alreadyStatic = -not $snapshot.DhcpEnabled
$sameIp = ($snapshot.IpAddress -eq $TargetIp)
if ($SkipIfAlreadyStatic -and $alreadyStatic -and $sameIp -and -not $Force) {
    Write-Host "Already static at $TargetIp on '$($snapshot.AdapterName)' — no change." -ForegroundColor Green
} else {
    Set-AdapterStaticIp -Snapshot $snapshot -NewIp $TargetIp -LogDir $logDir
    Start-Sleep -Seconds 2
    $snapshot = Get-AdapterNetworkSnapshot -InterfaceIndex $choice.Address.InterfaceIndex
    Write-Host "Static IP applied." -ForegroundColor Green
}

Set-YamlScalar -ConfigPath $sitePath -Key "pc_lan_ip" -Value $TargetIp
Set-YamlScalar -ConfigPath $sitePath -Key "pc_lan_static_enabled" -Value "true"

$siteCode = Read-SiteYamlValue -Key "outbound_site_code" -ProjectRoot $projectRoot -Default "site"
Write-RouterReservationGuide -OutPath (Join-Path $logDir "router_dhcp_reservation.txt") -Snapshot $snapshot -DeviceIp $deviceIp -SiteCode $siteCode

Write-Host ""
Write-Host "Connectivity checks:" -ForegroundColor Cyan
$okDevice = Test-Connection -ComputerName $deviceIp -Count 1 -Quiet -ErrorAction SilentlyContinue
$okInternet = Test-Connection -ComputerName "8.8.8.8" -Count 1 -Quiet -ErrorAction SilentlyContinue
Write-Host "  Ping device $deviceIp : $(if ($okDevice) { 'OK' } else { 'FAIL' })" -ForegroundColor $(if ($okDevice) { 'Green' } else { 'Red' })
Write-Host "  Ping internet 8.8.8.8 : $(if ($okInternet) { 'OK' } else { 'FAIL' })" -ForegroundColor $(if ($okInternet) { 'Green' } else { 'Red' })

if (-not $okDevice) {
    Write-Host ""
    Write-Host "WARNING: Cannot reach biometric device. Check cable/Wi-Fi and machine_sync_ip." -ForegroundColor Red
    exit 2
}

Write-Host ""
Write-Host "Done. Run 3-CONFIGURE_DEVICE.cmd next (firewall + live-push) if not already done." -ForegroundColor Green
exit 0
