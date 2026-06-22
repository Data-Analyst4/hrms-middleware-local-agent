param(
    [string]$Config = "configs/factory.yaml",
    [switch]$NoAutoStart,
    [switch]$NoTunnel,
    [switch]$NoStartNow,
    [switch]$InstallSqlServerPrereqs,
    [switch]$SkipPrereqInstall,
    [switch]$SkipSiteInit
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "scripts\lib\project_paths.ps1")

function Test-Python311OrNewer {
    $candidates = @(
        @{ Command = "python"; Prefix = @() },
        @{ Command = "py"; Prefix = @("-3.11") },
        @{ Command = "py"; Prefix = @("-3") }
    )
    foreach ($candidate in $candidates) {
        $cmd = Get-Command $candidate.Command -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            $args = @()
            $args += $candidate.Prefix
            $args += @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
            $versionText = (& $cmd.Source @args).Trim()
            if (-not $versionText) { continue }
            $version = [Version]$versionText
            if ($version -ge [Version]"3.11.0") { return $true }
        } catch { }
    }
    return $false
}

function Test-ConfigNeedsSqlServer {
    param([string]$ConfigPath)
    if (-not (Test-Path $ConfigPath)) { return $false }
    $content = Get-Content -Raw $ConfigPath
    return $content -match 'db_url\s*:\s*".*mssql\+pyodbc' -or $content -match "db_url\s*:\s*'.*mssql\+pyodbc"
}

function Get-IngressPortFromConfig {
    param([string]$ConfigPath)
    if (-not (Test-Path $ConfigPath)) { return 8080 }
    $content = Get-Content -Raw $ConfigPath
    if ($content -match 'ingress_port\s*:\s*(\d+)') { return [int]$Matches[1] }
    return 8080
}

function Add-GatewayFirewallRule {
    param([int]$Port)
    $ruleName = "HRMS Middleware Gateway $Port"
    try {
        New-NetFirewallRule `
            -DisplayName $ruleName `
            -Direction Inbound `
            -Protocol TCP `
            -Action Allow `
            -LocalPort $Port `
            -ErrorAction SilentlyContinue | Out-Null
        Write-Host "Firewall rule ready for TCP port $Port." -ForegroundColor Green
    } catch {
        Write-Warning "Could not create firewall rule for port ${Port}: $($_.Exception.Message)"
    }
}

function Install-WithWinget {
    param([string]$Id, [string]$DisplayName)
    Write-Host "Installing/checking $DisplayName..." -ForegroundColor Yellow
    $wingetArgs = @(
        "install", "--id", $Id, "-e", "--silent", "--disable-interactivity",
        "--accept-package-agreements", "--accept-source-agreements", "--force"
    )
    if (Test-IsAdmin) { $wingetArgs += @("--scope", "machine") }
    & winget @wingetArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install '$DisplayName' (package id: $Id)."
    }
}

$projectRoot = Get-ProjectRoot -ScriptRoot $PSScriptRoot
Set-Location $projectRoot

$enableAutoStart = -not $NoAutoStart
$enableTunnel = -not $NoTunnel
$startNow = -not $NoStartNow
$configAbsPath = Resolve-ConfigPath -Config $Config -ProjectRoot $projectRoot
$needsSqlServer = $InstallSqlServerPrereqs -or (Test-ConfigNeedsSqlServer -ConfigPath $configAbsPath)

if (-not $SkipSiteInit) {
    Ensure-SiteLocalConfig -ProjectRoot $projectRoot | Out-Null
}

$tunnelHostname = Read-SiteYamlValue -Key "cloudflare_public_hostname" -Default "v8-mw.k95foods.com" -ProjectRoot $projectRoot
$tunnelHostname = $tunnelHostname -replace '^https?://', '' -replace '/.*$', ''
$tunnelName = Read-SiteYamlValue -Key "cloudflare_tunnel_name" -Default "v8-middleware" -ProjectRoot $projectRoot
$tunnelPort = [int](Read-SiteYamlValue -Key "cloudflare_local_port" -Default "8080" -ProjectRoot $projectRoot)

if ($enableAutoStart -and -not (Test-IsAdmin)) {
    Write-Host "Re-launching with Administrator privileges for full one-click setup..." -ForegroundColor Yellow
    $argList = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-Config", "`"$Config`""
    )
    if ($NoAutoStart) { $argList += "-NoAutoStart" }
    if ($NoTunnel) { $argList += "-NoTunnel" }
    if ($NoStartNow) { $argList += "-NoStartNow" }
    if ($InstallSqlServerPrereqs) { $argList += "-InstallSqlServerPrereqs" }
    if ($SkipPrereqInstall) { $argList += "-SkipPrereqInstall" }
    if ($SkipSiteInit) { $argList += "-SkipSiteInit" }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $argList | Out-Null
    exit 0
}

Write-Host "== One-Click HRMS Middleware Setup ==" -ForegroundColor Cyan
Write-Host "Project: $projectRoot"
Write-Host "Config:  $configAbsPath"
Write-Host "Per-PC:  $(Get-SiteLocalConfigPath -ProjectRoot $projectRoot)"
if (-not (Test-IsWindows10OrLater)) {
    Write-Warning "Windows 10 or later is required."
}

Show-SiteConfigChecklist -ProjectRoot $projectRoot

if (-not $SkipPrereqInstall) {
    $hasWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)
    if (-not $hasWinget) {
        Write-Warning "winget not found (common on older Windows 10). Install Python 3.11 manually from python.org, then re-run."
        if (-not (Test-Python311OrNewer)) {
            throw "Python 3.11+ required. Install Python, then re-run this script with -SkipPrereqInstall"
        }
    } else {
        if (-not (Test-Python311OrNewer)) {
            Install-WithWinget -Id "Python.Python.3.11" -DisplayName "Python 3.11"
        } else {
            Write-Host "Python 3.11+ already installed." -ForegroundColor Green
        }
        Install-WithWinget -Id "Microsoft.VCRedist.2015+.x64" -DisplayName "Visual C++ Runtime"
        if ($needsSqlServer) {
            Install-WithWinget -Id "Microsoft.msodbcsql.18" -DisplayName "ODBC Driver 18 for SQL Server"
        }
    }
} else {
    Write-Host "Skipping prerequisite installation by request." -ForegroundColor Yellow
}

$installArgs = @{ Config = $Config }
if ($needsSqlServer) { $installArgs.InstallSqlServerDeps = $true }
& (Join-Path $projectRoot "scripts\install_local_pc.ps1") @installArgs

if (Test-IsAdmin) {
    $ingressPort = Get-IngressPortFromConfig -ConfigPath $configAbsPath
    Add-GatewayFirewallRule -Port $ingressPort
    if ($ingressPort -ne 8081) { Add-GatewayFirewallRule -Port 8081 }

    $deviceIp = Read-SiteYamlValue -Key "device_lan_ip_for_firewall" -ProjectRoot $projectRoot
    if (-not $deviceIp) {
        $deviceIp = Read-SiteYamlValue -Key "machine_sync_ip" -ProjectRoot $projectRoot
    }
    if ($deviceIp) {
        $fwScript = Join-Path $projectRoot "scripts\fix_live_push_firewall.ps1"
        if (Test-Path $fwScript) {
            Write-Host "Applying live-push firewall rule for device $deviceIp..." -ForegroundColor Cyan
            & $fwScript -DeviceIp $deviceIp -Port 8081
        }
    }
}

if ($enableAutoStart) {
    Write-Host ""
    Write-Host "== Registering boot auto-start (middleware supervisor) ==" -ForegroundColor Cyan
    & (Join-Path $projectRoot "scripts\setup_autostart.ps1") -Config $Config -StartNow:$startNow
} elseif ($startNow) {
    Write-Host "Starting middleware stack now (manual mode)..." -ForegroundColor Yellow
    Start-Process powershell.exe `
        -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", "`"$projectRoot\scripts\run_stack_forever.ps1`"",
            "-Config", "`"$Config`""
        ) `
        -WindowStyle Hidden | Out-Null
}

if ($enableAutoStart -and $enableTunnel -and (Test-IsAdmin)) {
    Write-Host ""
    Write-Host "== Registering Cloudflare tunnel auto-start ==" -ForegroundColor Cyan
    & (Join-Path $projectRoot "scripts\install_tunnel_stack.ps1") `
        -TunnelName $tunnelName `
        -PublicHostname $tunnelHostname `
        -LocalPort $tunnelPort `
        -StartNow:$startNow
} elseif ($enableTunnel -and -not (Test-IsAdmin)) {
    Write-Warning "Tunnel autostart skipped (Administrator required)."
}

$ingressPort = Get-IngressPortFromConfig -ConfigPath $configAbsPath

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "API base: http://127.0.0.1:$ingressPort"
Write-Host "Dashboard: http://127.0.0.1:$ingressPort/dashboard"
if ($enableAutoStart) {
    Write-Host "Auto-start on boot: ENABLED"
    Write-Host "  Middleware task: HRMS-Middleware-Supervisor"
    if ($enableTunnel) {
        Write-Host "  Tunnel hostname: https://$tunnelHostname"
        Write-Host "  Tunnel watchdog: V8-Cloudflare-Tunnel-Watchdog"
    }
    Write-Host "Supervisor log: $projectRoot\var\logs\supervisor.log"
}
Write-Host ""
Write-Host "If you moved this folder, re-run SETUP_FACTORY_AUTOSTART.cmd to fix scheduled tasks."
Write-Host ""
Write-Host "Checking stack status in a few seconds..."
Start-Sleep -Seconds 8
& (Join-Path $projectRoot "scripts\check_stack_status.ps1") -Config $Config
