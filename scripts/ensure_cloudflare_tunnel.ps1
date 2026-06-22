# Watchdog: restart cloudflared (service or scheduled-task runner) if tunnel health fails.
param(
    [string]$PublicHostname = "v8-mw.k95foods.com",
    [string]$ServiceName = "Cloudflared",
    [int]$LocalPort = 8080,
    [string]$LogFile = "var/logs/cloudflared-watchdog.log",
    [string]$SupervisorTaskName = "HRMS-Middleware-Supervisor",
    [string]$TunnelMode = "",
    [string]$RunnerTaskName = "V8-Cloudflare-Tunnel-Runner"
)

$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "lib\cloudflared_windows.ps1")

$script:CloudflaredExeForWatchdog = ""
foreach ($candidate in @(
        "C:\Program Files (x86)\cloudflared\cloudflared.exe",
        "C:\Program Files\cloudflared\cloudflared.exe",
        (Get-Command cloudflared.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
    )) {
    if ($candidate -and (Test-Path $candidate)) {
        $script:CloudflaredExeForWatchdog = $candidate
        break
    }
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logAbs = Join-Path $projectRoot $LogFile
$logDir = Split-Path $logAbs -Parent
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$modeFile = Join-Path $projectRoot "var\logs\cloudflared-mode.txt"
if (-not $TunnelMode -and (Test-Path $modeFile)) {
    $TunnelMode = (Get-Content -Raw $modeFile).Trim()
}
if (-not $TunnelMode) { $TunnelMode = "service" }

function Write-Log([string]$Message) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
    Add-Content -Path $logAbs -Value $line -Encoding UTF8
}

function Test-LocalGateway {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$LocalPort/health" -UseBasicParsing -TimeoutSec 8
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Test-PublicTunnel {
    try {
        $url = "https://$($PublicHostname.TrimEnd('/'))/health"
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 20
        return ($r.StatusCode -eq 200 -and $r.Content -match '"status"\s*:\s*"ok"')
    } catch { return $false }
}

function Restart-TunnelService {
    foreach ($name in @($ServiceName, "Cloudflared", "cloudflared")) {
        if (-not (Test-ScServiceExists $name)) { continue }
        if (Restart-CloudflaredServiceSafe -ServiceNameValue $name -WarmupSeconds 12 -CloudflaredExe $script:CloudflaredExeForWatchdog) {
            Write-Log "Restarted service '$name'."
            return $true
        }
        Write-Log "Failed to restart service '$name'."
    }
    return $false
}

function Restart-TunnelRunner {
    Stop-CloudflaredProcesses
    Start-Sleep -Seconds 2
    $task = Get-ScheduledTask -TaskName $RunnerTaskName -ErrorAction SilentlyContinue
    if ($task) {
        Start-ScheduledTask -TaskName $RunnerTaskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 8
        if (Get-Process cloudflared -ErrorAction SilentlyContinue) {
            Write-Log "Restarted runner task '$RunnerTaskName'."
            return $true
        }
    }
    Write-Log "Runner task '$RunnerTaskName' not available or process did not start."
    return $false
}

function Restart-SupervisorTask {
    $task = Get-ScheduledTask -TaskName $SupervisorTaskName -ErrorAction SilentlyContinue
    if (-not $task) { return $false }
    try {
        Stop-ScheduledTask -TaskName $SupervisorTaskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
        Start-ScheduledTask -TaskName $SupervisorTaskName
        Write-Log "Restarted supervisor task '$SupervisorTaskName'."
        return $true
    } catch {
        Write-Log "Failed to restart supervisor: $($_.Exception.Message)"
        return $false
    }
}

$localOk = Test-LocalGateway
if (-not $localOk) {
    Write-Log "Local middleware :$LocalPort not healthy - restarting supervisor."
    Restart-SupervisorTask | Out-Null
    Start-Sleep -Seconds 15
    $localOk = Test-LocalGateway
}

if (Test-PublicTunnel) {
    Write-Log "OK https://$PublicHostname/health (mode=$TunnelMode local=$localOk)"
    exit 0
}

if ($localOk -and $TunnelMode -eq "service") {
    Start-Sleep -Seconds 15
    if (Test-PublicTunnel) {
        Write-Log "OK after warmup https://$PublicHostname/health"
        exit 0
    }
}

Write-Log "UNHEALTHY https://$PublicHostname/health - restarting tunnel (mode=$TunnelMode)."
$restarted = $false
if ($TunnelMode -eq "runner") {
    $restarted = Restart-TunnelRunner
} else {
    $restarted = Restart-TunnelService
    if (-not $restarted) {
        $restarted = Restart-TunnelRunner
    }
}

if ($restarted -and (Test-PublicTunnel)) {
    Write-Log "Recovered after tunnel restart."
    exit 0
}

Write-Log "Still unhealthy after restart (local=$localOk)."

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$configAbs = Join-Path $projectRoot "configs\factory.yaml"
if ((Test-Path $pythonExe) -and (Test-Path $configAbs)) {
    try {
        $ctx = @{ hostname = $PublicHostname; local_ok = $localOk; tunnel_mode = $TunnelMode } | ConvertTo-Json -Compress
        & $pythonExe "scripts/send_alert.py" `
            "--config" $configAbs `
            "--event" "tunnel_unhealthy" `
            "--title" "Cloudflare tunnel down" `
            "--message" "Public tunnel https://$PublicHostname/health is unhealthy after restart. ERP cannot reach this site until fixed." `
            "--context-json" $ctx | Out-Null
    } catch {
        Write-Log "Tunnel alert send failed: $($_.Exception.Message)"
    }
}

exit 1
