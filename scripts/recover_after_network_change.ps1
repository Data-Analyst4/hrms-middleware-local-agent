# Network change recovery: verify PC <-> attendance machine connectivity and optional live-push heal.
param(
    [switch]$FixLivePush,
    [switch]$SkipPublicCheck
)

$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "lib\project_paths.ps1")
. (Join-Path $PSScriptRoot "lib\site_secrets.ps1")
. (Join-Path $PSScriptRoot "lib\lan_network.ps1")

$projectRoot = Get-ProjectRoot -ScriptRoot $PSScriptRoot
$sitePath = Get-SiteLocalConfigPath -ProjectRoot $projectRoot
$configPath = Resolve-ConfigPath -Config "configs/factory.yaml" -ProjectRoot $projectRoot
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"

$machineIp = Read-SiteYamlValue -Key "machine_sync_ip" -ProjectRoot $projectRoot
$machinePort = [int](Read-SiteYamlValue -Key "machine_sync_port" -ProjectRoot $projectRoot -Default "5005")
$pcLanIp = Read-SiteYamlValue -Key "pc_lan_ip" -ProjectRoot $projectRoot
$hostname = Read-SiteYamlValue -Key "cloudflare_public_hostname" -ProjectRoot $projectRoot
$ingressPort = [int](Read-SiteYamlValue -Key "ingress_port" -ProjectRoot $projectRoot -Default "8080")

function Write-Step([string]$Title) {
    Write-Host ""
    Write-Host "== $Title ==" -ForegroundColor Cyan
}

function Write-Ok([string]$Msg) { Write-Host "  [OK] $Msg" -ForegroundColor Green }
function Write-Warn([string]$Msg) { Write-Host "  [!!] $Msg" -ForegroundColor Yellow }
function Write-Fail([string]$Msg) { Write-Host "  [FAIL] $Msg" -ForegroundColor Red }

Write-Host ""
Write-Host "HR Middleware — network / machine connection recovery" -ForegroundColor Green
Write-Host "Project: $projectRoot" -ForegroundColor Gray
Write-Host "Guide:  docs\ROUTER_AND_LAN_IP_RECOVERY.md" -ForegroundColor Gray

if (-not (Test-Path $sitePath)) {
    Write-Fail "Missing configs\site.local.yaml — run 1-CONFIGURE_SITE.cmd first."
    exit 1
}

if (-not $machineIp) {
    Write-Fail "machine_sync_ip is empty in site.local.yaml — set the biometric device IP."
    exit 1
}

Write-Step "1) PC network (ipconfig summary)"
$adapters = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {
        $_.IPAddress -notmatch '^(127\.|169\.254\.)'
    })
$pcIps = @($adapters | ForEach-Object { $_.IPAddress } | Sort-Object -Unique)
foreach ($ip in $pcIps) {
    Write-Host "  PC IPv4: $ip"
}
if ($pcLanIp) {
    Write-Host "  Config pc_lan_ip: $pcLanIp" -ForegroundColor Gray
}

Write-Step "2) Configured attendance machine"
Write-Host "  machine_sync_ip:   $machineIp"
Write-Host "  machine_sync_port: $machinePort"

$conflict = $pcIps -contains $machineIp
if ($conflict) {
    Write-Fail "IP CONFLICT: PC and machine both use $machineIp — Windows pings itself, not the device."
    Write-Warn "Set machine to a different IP (e.g. 192.168.1.100) on device menu, update site.local.yaml."
} else {
    Write-Ok "PC IP differs from machine_sync_ip"
}

Write-Step "3) Ping machine"
$pingOk = Test-Connection -ComputerName $machineIp -Count 2 -Quiet -ErrorAction SilentlyContinue
if ($pingOk) { Write-Ok "Ping $machineIp" } else { Write-Fail "Cannot ping $machineIp" }

Write-Step "4) TCP port $machinePort (SDK)"
try {
    $tcp = Test-NetConnection -ComputerName $machineIp -Port $machinePort -WarningAction SilentlyContinue
    Write-Host "  SourceAddress: $($tcp.SourceAddress)"
    Write-Host "  RemoteAddress: $($tcp.RemoteAddress)"
    if ($tcp.SourceAddress -eq $tcp.RemoteAddress) {
        Write-Fail "Source and Remote are the same — fix IP conflict before continuing."
    } elseif ($tcp.TcpTestSucceeded) {
        Write-Ok "Port $machinePort open on $machineIp"
    } else {
        Write-Fail "Port $machinePort not reachable — check machine menu (port 5005, DHCP OFF, reboot device)."
    }
} catch {
    Write-Fail "TCP test error: $($_.Exception.Message)"
}

Write-Step "5) Local middleware health"
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$ingressPort/health" -TimeoutSec 5
    Write-Ok "http://127.0.0.1:$ingressPort/health"
} catch {
    Write-Fail "Local gateway not responding — run RESTART_STACK.cmd"
}

if (-not $SkipPublicCheck -and $hostname) {
    Write-Step "6) Public tunnel (ISP WAN changes do not affect this if tunnel is up)"
    try {
        $pub = Invoke-RestMethod -Uri "https://$hostname/health" -TimeoutSec 15
        Write-Ok "https://$hostname/health"
    } catch {
        Write-Warn "Public health failed — run REPAIR_CLOUDFLARE.cmd if ERP access is needed."
    }
}

if (Test-Path $pythonExe) {
    Write-Step "7) Device live-push target"
    $pushArgs = @("scripts\ensure_device_live_push.py", "--config", $configPath)
    if ($FixLivePush) { $pushArgs += "--fix" }
    $pushOut = & $pythonExe @pushArgs 2>&1 | Out-String
    Write-Host $pushOut.Trim()
    if ($FixLivePush -and $LASTEXITCODE -eq 0) {
        Write-Ok "Live-push check/heal completed"
    } elseif (-not $FixLivePush -and $pushOut -match '"ok"\s*:\s*false') {
        Write-Warn "Live-push drift — re-run: RECOVER_AFTER_NETWORK_CHANGE.cmd -FixLivePush"
        Write-Warn "Or run 3-CONFIGURE_DEVICE.cmd as Administrator"
    }
} else {
    Write-Warn "Python venv not found — run 2-INSTALL_FACTORY.cmd"
}

Write-Step "Next steps if machine still not connected"
Write-Host @"
  1. Edit configs\site.local.yaml (machine_sync_ip = device IP only)
  2. Run 4-CONFIGURE_LAN_IP.cmd as Administrator
  3. Run 3-CONFIGURE_DEVICE.cmd as Administrator
  4. RESTART_STACK.cmd then CHECK_STATUS.cmd
  5. Test SDK: http://127.0.0.1:$ingressPort/docs -> POST /api/machine/test-connection

  Full guide: docs\ROUTER_AND_LAN_IP_RECOVERY.md
"@

if ($conflict) { exit 2 }
if (-not $pingOk) { exit 2 }
exit 0
