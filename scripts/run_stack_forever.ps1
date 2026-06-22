param(
    [string]$Config = "configs/factory.yaml",
    [int]$CheckIntervalSeconds = 5,
    [int]$WebhookIntervalSeconds = 60,
    [int]$DevicePullIntervalSeconds = 30,
    [int]$StartupDelaySeconds = 20,
    [int]$LivenessIntervalSeconds = 30,
    [int]$LivePushHealIntervalSeconds = 0,
    [int]$GatewayLivenessTimeoutSeconds = 10,
    [int]$WorkerHealthStaleSeconds = 120,
    [int]$FkHealthStaleSeconds = 600
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

$configAbs = if ([System.IO.Path]::IsPathRooted($Config)) {
    $Config
} else {
    (Resolve-Path (Join-Path $projectRoot $Config) -ErrorAction Stop).Path
}

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Virtual environment not found at $pythonExe. Run install script first."
}

$logDir = Join-Path $projectRoot "var\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "supervisor.log"
$supervisorHealthFile = Join-Path $projectRoot "var\supervisor\health.json"

function Write-Log {
    param([string]$Message)
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
    try {
        Add-Content -Path $logFile -Value $line -Encoding UTF8
    } catch {
        # Best effort when running as SYSTEM with locked files.
    }
}

function Read-YamlValue {
    param(
        [string]$ConfigPath,
        [string]$Key,
        [string]$Default = ""
    )
    if (-not (Test-Path $ConfigPath)) { return $Default }
    $content = Get-Content -Raw $ConfigPath
    $pattern = "(?m)^\s*$([regex]::Escape($Key))\s*:\s*(.+?)\s*$"
    if ($content -match $pattern) {
        return $Matches[1].Trim().Trim('"').Trim("'")
    }
    return $Default
}

function Read-YamlBool {
    param(
        [string]$ConfigPath,
        [string]$Key,
        [bool]$Default = $false
    )
    $raw = Read-YamlValue -ConfigPath $ConfigPath -Key $Key -Default ""
    if (-not $raw) { return $Default }
    switch ($raw.ToLowerInvariant()) {
        "true" { return $true }
        "1" { return $true }
        "yes" { return $true }
        "false" { return $false }
        "0" { return $false }
        "no" { return $false }
        default { return $Default }
    }
}

function Write-SupervisorHealth {
    param([hashtable]$Extra = @{})
    $payload = @{
        updated_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        config = $configAbs
    }
    foreach ($k in $Extra.Keys) {
        $payload[$k] = $Extra[$k]
    }
    $dir = Split-Path $supervisorHealthFile -Parent
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    ($payload | ConvertTo-Json -Compress) | Set-Content -Path $supervisorHealthFile -Encoding UTF8
}

function Wait-NetworkReady {
    param([int]$MaxWaitSeconds)
    if ($MaxWaitSeconds -le 0) { return }
    $deadline = (Get-Date).AddSeconds($MaxWaitSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $ping = Test-Connection -ComputerName "8.8.8.8" -Count 1 -Quiet -ErrorAction SilentlyContinue
            if ($ping) {
                Write-Log "Network ready."
                return
            }
        } catch {
            # retry
        }
        Start-Sleep -Seconds 3
    }
    Write-Log "Network wait timed out after ${MaxWaitSeconds}s; continuing anyway."
}

function Test-TcpPortOpen {
    param([int]$Port)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok = $async.AsyncWaitHandle.WaitOne(2000, $false)
        if ($ok -and $client.Connected) {
            $client.Close()
            return $true
        }
        $client.Close()
    } catch {
        return $false
    }
    return $false
}

function Test-GatewayHealth {
    param([int]$Port, [int]$TimeoutSec = 8)
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec $TimeoutSec
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Test-HealthFileFresh {
    param(
        [string]$Path,
        [int]$MaxAgeSeconds
    )
    if (-not (Test-Path $Path)) { return $false }
    try {
        $raw = Get-Content -Raw $Path | ConvertFrom-Json
        if (-not $raw.updated_at) { return $false }
        $updated = [datetime]::ParseExact($raw.updated_at, "yyyy-MM-dd HH:mm:ss", $null)
        return ((Get-Date) - $updated).TotalSeconds -le $MaxAgeSeconds
    } catch {
        return $false
    }
}

function Stop-ManagedProcess {
    param([System.Diagnostics.Process]$Proc)
    if ($null -eq $Proc -or $Proc.HasExited) { return }
    try {
        Stop-Process -Id $Proc.Id -Force -ErrorAction SilentlyContinue
        Write-Log "Stopped pid=$($Proc.Id)"
    } catch {
        Write-Log "Failed to stop pid=$($Proc.Id): $($_.Exception.Message)"
    }
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$ScriptPath,
        [string]$ConfigPath
    )

    $args = @($ScriptPath, "--config", $ConfigPath)
    $proc = Start-Process `
        -FilePath $pythonExe `
        -ArgumentList $args `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -PassThru

    Write-Log "Started $Name pid=$($proc.Id)"
    return $proc
}

$ingressPort = [int](Read-YamlValue -ConfigPath $configAbs -Key "ingress_port" -Default "8080")
$fkPort = [int](Read-YamlValue -ConfigPath $configAbs -Key "fk_web_listener_port" -Default "8081")
$outboundEnabled = Read-YamlBool -ConfigPath $configAbs -Key "outbound_relay_enabled" -Default $true
$livePushHealEnabled = Read-YamlBool -ConfigPath $configAbs -Key "live_push_auto_heal_enabled" -Default $true
$networkWait = [int](Read-YamlValue -ConfigPath $configAbs -Key "network_ready_max_wait_seconds" -Default "120")
$workerHealthFile = Join-Path $projectRoot (Read-YamlValue -ConfigPath $configAbs -Key "worker_health_file" -Default "var/worker/health.json")
$fkHealthFile = Join-Path $projectRoot (Read-YamlValue -ConfigPath $configAbs -Key "fk_health_file" -Default "var/fk_listener/health.json")
if ($LivePushHealIntervalSeconds -le 0) {
    $LivePushHealIntervalSeconds = [int](Read-YamlValue -ConfigPath $configAbs -Key "live_push_heal_interval_seconds" -Default "900")
}

Write-Log "Supervisor starting. Config=$configAbs Project=$projectRoot"

if ($StartupDelaySeconds -gt 0) {
    Write-Log "Waiting $StartupDelaySeconds seconds for services after boot..."
    Start-Sleep -Seconds $StartupDelaySeconds
}

Wait-NetworkReady -MaxWaitSeconds $networkWait

$gateway = Start-ManagedProcess -Name "gateway" -ScriptPath "scripts/run_gateway.py" -ConfigPath $configAbs
$fkListener = Start-ManagedProcess -Name "fk-listener" -ScriptPath "scripts/run_fk_web_listener.py" -ConfigPath $configAbs
$worker = $null
if ($outboundEnabled) {
    $worker = Start-ManagedProcess -Name "worker" -ScriptPath "scripts/run_worker.py" -ConfigPath $configAbs
} else {
    Write-Log "outbound_relay_enabled=false; worker not started."
}

$nextWebhook = (Get-Date)
$nextDevicePull = (Get-Date)
$nextLiveness = (Get-Date)
$nextLivePushHeal = (Get-Date).AddSeconds(60)

try {
    while ($true) {
        if ($gateway.HasExited) {
            Write-Log "Gateway exited code=$($gateway.ExitCode). Restarting..."
            Start-Sleep -Seconds 2
            $gateway = Start-ManagedProcess -Name "gateway" -ScriptPath "scripts/run_gateway.py" -ConfigPath $configAbs
        }

        if ($outboundEnabled -and $null -ne $worker -and $worker.HasExited) {
            Write-Log "Worker exited code=$($worker.ExitCode). Restarting..."
            Start-Sleep -Seconds 2
            $worker = Start-ManagedProcess -Name "worker" -ScriptPath "scripts/run_worker.py" -ConfigPath $configAbs
        }

        if ($fkListener.HasExited) {
            Write-Log "FK listener exited code=$($fkListener.ExitCode). Restarting..."
            Start-Sleep -Seconds 2
            $fkListener = Start-ManagedProcess -Name "fk-listener" -ScriptPath "scripts/run_fk_web_listener.py" -ConfigPath $configAbs
        }

        if ((Get-Date) -ge $nextLiveness) {
            if (-not (Test-GatewayHealth -Port $ingressPort -TimeoutSec $GatewayLivenessTimeoutSeconds)) {
                Write-Log "Liveness: gateway unhealthy on :$ingressPort - restarting."
                Stop-ManagedProcess -Proc $gateway
                Start-Sleep -Seconds 2
                $gateway = Start-ManagedProcess -Name "gateway" -ScriptPath "scripts/run_gateway.py" -ConfigPath $configAbs
            }

            if (-not (Test-TcpPortOpen -Port $fkPort)) {
                Write-Log "Liveness: FK listener port :$fkPort closed - restarting."
                Stop-ManagedProcess -Proc $fkListener
                Start-Sleep -Seconds 2
                $fkListener = Start-ManagedProcess -Name "fk-listener" -ScriptPath "scripts/run_fk_web_listener.py" -ConfigPath $configAbs
            } elseif (-not (Test-HealthFileFresh -Path $fkHealthFile -MaxAgeSeconds $FkHealthStaleSeconds)) {
                Write-Log "Liveness: FK health stale (no recent device traffic on :$fkPort). Check device push target."
            }

            if ($outboundEnabled -and $null -ne $worker -and -not $worker.HasExited) {
                if (-not (Test-HealthFileFresh -Path $workerHealthFile -MaxAgeSeconds $WorkerHealthStaleSeconds)) {
                    Write-Log "Liveness: worker health stale - restarting worker."
                    Stop-ManagedProcess -Proc $worker
                    Start-Sleep -Seconds 2
                    $worker = Start-ManagedProcess -Name "worker" -ScriptPath "scripts/run_worker.py" -ConfigPath $configAbs
                }
            }

            Write-SupervisorHealth @{
                gateway_port = $ingressPort
                fk_port = $fkPort
                outbound_enabled = $outboundEnabled
            }
            $nextLiveness = (Get-Date).AddSeconds($LivenessIntervalSeconds)
        }

        if ($livePushHealEnabled -and (Get-Date) -ge $nextLivePushHeal) {
            try {
                $healOutput = & $pythonExe "scripts/ensure_device_live_push.py" "--config" $configAbs "--fix" "--quiet" 2>&1
                if ($LASTEXITCODE -ne 0) {
                    Write-Log "Live push heal exit=$LASTEXITCODE output=$healOutput"
                }
            } catch {
                Write-Log "Live push heal failed: $($_.Exception.Message)"
            }
            $nextLivePushHeal = (Get-Date).AddSeconds($LivePushHealIntervalSeconds)
        }

        if ((Get-Date) -ge $nextWebhook) {
            try {
                & $pythonExe "scripts/run_webhook_dispatch.py" "--config" $configAbs | Out-Null
            } catch {
                Write-Log "Webhook dispatch run failed: $($_.Exception.Message)"
            }
            $nextWebhook = (Get-Date).AddSeconds($WebhookIntervalSeconds)
        }

        if ((Get-Date) -ge $nextDevicePull) {
            try {
                $pullOutput = & $pythonExe "scripts/pull_device_logs_to_db.py" "--config" $configAbs "--incremental" "--limit" "200" 2>&1
                if ($LASTEXITCODE -ne 0) {
                    Write-Log "Device log pull exit=$LASTEXITCODE output=$pullOutput"
                }
            } catch {
                Write-Log "Device log pull failed: $($_.Exception.Message)"
            }
            $nextDevicePull = (Get-Date).AddSeconds($DevicePullIntervalSeconds)
        }

        Start-Sleep -Seconds $CheckIntervalSeconds
    }
}
finally {
    Write-Log "Supervisor stopping. Cleaning up child processes..."
    foreach ($proc in @($gateway, $fkListener, $worker)) {
        Stop-ManagedProcess -Proc $proc
    }
}
