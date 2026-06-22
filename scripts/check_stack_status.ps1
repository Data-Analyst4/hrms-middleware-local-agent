param(
    [string]$Config = "configs/factory.yaml",
    [string]$TaskName = "HRMS-Middleware-Supervisor",
    [string]$PublicHostname = "",
    [switch]$SkipDeviceCheck
)

$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "lib\project_paths.ps1")

function Get-YamlValue {
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

function Read-HealthJson {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    try {
        return Get-Content -Raw $Path | ConvertFrom-Json
    } catch {
        return $null
    }
}

$projectRoot = Get-ProjectRoot -ScriptRoot $PSScriptRoot
$configPath = Resolve-ConfigPath -Config $Config -ProjectRoot $projectRoot
$port = [int](Get-YamlValue -ConfigPath $configPath -Key "ingress_port" -Default "8080")
$fkPort = [int](Get-YamlValue -ConfigPath $configPath -Key "fk_web_listener_port" -Default "8081")
$healthUrl = "http://127.0.0.1:$port/health"
$logFile = Join-Path $projectRoot "var\logs\supervisor.log"
$workerHealthPath = Join-Path $projectRoot (Get-YamlValue -ConfigPath $configPath -Key "worker_health_file" -Default "var/worker/health.json")
$fkHealthPath = Join-Path $projectRoot (Get-YamlValue -ConfigPath $configPath -Key "fk_health_file" -Default "var/fk_listener/health.json")
$supervisorHealthPath = Join-Path $projectRoot (Get-YamlValue -ConfigPath $configPath -Key "supervisor_health_file" -Default "var/supervisor/health.json")

if (-not $PublicHostname) {
    $PublicHostname = Read-SiteYamlValue -Key "cloudflare_public_hostname" -ProjectRoot $projectRoot
    if (-not $PublicHostname) {
        $PublicHostname = $env:CLOUDFLARE_PUBLIC_HOSTNAME
    }
    if (-not $PublicHostname) {
        $envFile = Join-Path $projectRoot "configs\integration.local.env"
        if (Test-Path $envFile) {
            foreach ($line in Get-Content $envFile) {
                if ($line -match '^\s*CLOUDFLARE_PUBLIC_HOSTNAME\s*=\s*(.+)\s*$') {
                    $PublicHostname = $Matches[1].Trim().Trim('"')
                    break
                }
            }
        }
    }
    if (-not $PublicHostname) {
        $PublicHostname = "v8-mw.k95foods.com"
    }
}
$PublicHostname = $PublicHostname -replace '^https?://', '' -replace '/.*$', ''

Write-Host "== HRMS Middleware Stack Status ==" -ForegroundColor Cyan
Write-Host "Project: $projectRoot"
Write-Host "Config:  $configPath"
Write-Host ""

$allOk = $true

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    $state = $task.State
    $color = if ($state -eq "Running") { "Green" } else { "Yellow" }
    Write-Host "Scheduled task '$TaskName': $state (last result: $($info.LastTaskResult))" -ForegroundColor $color
} else {
    Write-Host "Scheduled task '$TaskName': NOT REGISTERED" -ForegroundColor Yellow
    Write-Host "  Run INSTALL_ONE_CLICK.cmd to register auto-start on boot." -ForegroundColor Gray
}

$processNames = @("run_gateway.py", "run_worker.py", "run_fk_web_listener.py", "run_stack_forever.ps1")
Write-Host ""
Write-Host "Processes:"
foreach ($match in $processNames) {
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$match*" }
    if ($procs) {
        foreach ($p in $procs) {
            Write-Host "  [OK] $($p.Name) pid=$($p.ProcessId) ($match)" -ForegroundColor Green
        }
    } else {
        Write-Host "  [--] $match not running" -ForegroundColor DarkGray
        if ($match -ne "run_stack_forever.ps1") {
            $allOk = $false
        }
    }
}

Write-Host ""
Write-Host "Gateway health: $healthUrl"
try {
    $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 5
    if ($response.StatusCode -eq 200) {
        Write-Host "  [OK] Gateway responding (HTTP $($response.StatusCode))" -ForegroundColor Green
        try {
            $body = $response.Content | ConvertFrom-Json
            if ($body.counts) {
                Write-Host "  Outbox: PENDING=$($body.counts.PENDING) FAILED=$($body.counts.FAILED) SENT=$($body.counts.SENT)" -ForegroundColor Gray
                if ([int]$body.counts.FAILED -gt 0) {
                    Write-Host "  [!!] FAILED outbox rows present - worker will replay on schedule" -ForegroundColor Yellow
                }
            }
        } catch {
            # optional counts in health payload
        }
    } else {
        Write-Host "  [!!] Gateway returned HTTP $($response.StatusCode)" -ForegroundColor Red
        $allOk = $false
    }
} catch {
    Write-Host "  [!!] Gateway not reachable: $($_.Exception.Message)" -ForegroundColor Red
    $allOk = $false
}

Write-Host ""
Write-Host "FK live-push listener: 127.0.0.1:$fkPort"
if (Test-TcpPortOpen -Port $fkPort) {
    Write-Host "  [OK] Port $fkPort accepting connections" -ForegroundColor Green
} else {
    Write-Host "  [!!] Port $fkPort not open" -ForegroundColor Red
    $allOk = $false
}
$fkHealth = Read-HealthJson -Path $fkHealthPath
if ($fkHealth) {
    Write-Host "  Last FK event: $($fkHealth.last_event) at $($fkHealth.updated_at)" -ForegroundColor Gray
    if ($fkHealth.last_punch_at) {
        Write-Host "  Last punch: $($fkHealth.last_punch_at)" -ForegroundColor Gray
    }
} else {
    Write-Host "  [--] No FK health file yet ($fkHealthPath)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Outbound worker:"
$workerHealth = Read-HealthJson -Path $workerHealthPath
if ($workerHealth) {
    Write-Host "  Updated: $($workerHealth.updated_at)" -ForegroundColor Gray
    if ($workerHealth.counts) {
        Write-Host "  Outbox counts: $($workerHealth.counts | ConvertTo-Json -Compress)" -ForegroundColor Gray
        if ([int]$workerHealth.counts.FAILED -gt 0) {
            Write-Host "  [!!] FAILED=$($workerHealth.counts.FAILED)" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "  [--] Worker health file missing ($workerHealthPath)" -ForegroundColor DarkGray
}

$supervisorHealth = Read-HealthJson -Path $supervisorHealthPath
if ($supervisorHealth) {
    Write-Host "Supervisor health updated: $($supervisorHealth.updated_at)" -ForegroundColor Gray
}

if (Test-Path $logFile) {
    Write-Host ""
    Write-Host "Recent supervisor log (last 8 lines):"
    Get-Content $logFile -Tail 8 -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "  $_" -ForegroundColor DarkGray
    }
} else {
    Write-Host ""
    Write-Host "Supervisor log not found yet: $logFile" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Cloudflare tunnel ($PublicHostname):"
$tunnelTask = Get-ScheduledTask -TaskName "V8-Cloudflare-Tunnel-Watchdog" -ErrorAction SilentlyContinue
if ($tunnelTask) {
    Write-Host "  [OK] Watchdog task: $($tunnelTask.State)" -ForegroundColor Green
} else {
    Write-Host "  [--] Watchdog task not registered" -ForegroundColor Yellow
}
$cfSvc = Get-Service -Name "Cloudflared","cloudflared" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($cfSvc) {
    $svcColor = if ($cfSvc.Status -eq "Running") { "Green" } else { "Red" }
    Write-Host "  [$($cfSvc.Status)] cloudflared service ($($cfSvc.StartType))" -ForegroundColor $svcColor
    if ($cfSvc.Status -ne "Running") { $allOk = $false }
} else {
    $cfProc = Get-Process cloudflared -ErrorAction SilentlyContinue
    if ($cfProc) {
        Write-Host "  [OK] cloudflared process pid=$($cfProc.Id) (manual)" -ForegroundColor Green
    } else {
        Write-Host "  [--] cloudflared not running" -ForegroundColor Yellow
    }
}
try {
    $tunnelHealth = Invoke-WebRequest -Uri "https://$PublicHostname/health" -UseBasicParsing -TimeoutSec 15
    if ($tunnelHealth.StatusCode -eq 200) {
        Write-Host "  [OK] Public tunnel health HTTP 200" -ForegroundColor Green
    } else {
        Write-Host "  [!!] Public tunnel HTTP $($tunnelHealth.StatusCode)" -ForegroundColor Red
        $allOk = $false
    }
} catch {
    Write-Host "  [!!] Public tunnel unreachable: $($_.Exception.Message)" -ForegroundColor Red
    $allOk = $false
}

Write-Host ""
Write-Host "Live push target (device -> this PC):"
if (-not $SkipDeviceCheck) {
try {
    $pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (Test-Path $pythonExe) {
        & $pythonExe "scripts/ensure_device_live_push.py" "--config" $configPath "--quiet" 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] Device push target matches this PC" -ForegroundColor Green
        } else {
            Write-Host "  [!!] Device push drift - run: python scripts/ensure_device_live_push.py --config $Config --fix" -ForegroundColor Red
            $allOk = $false
        }
    }
} catch {
    Write-Host "  [--] Could not verify live push: $($_.Exception.Message)" -ForegroundColor Yellow
}
} else {
    Write-Host "  [--] Skipped (use full check without -SkipDeviceCheck)" -ForegroundColor DarkGray
}

Write-Host ""
if ($allOk) {
    Write-Host "Overall: RUNNING" -ForegroundColor Green
    exit 0
}

Write-Host "Overall: NOT FULLY RUNNING" -ForegroundColor Yellow
Write-Host "Fix: START_TUNNEL_NOW.cmd or REPAIR_CLOUDFLARE.cmd (Admin) for tunnel." -ForegroundColor Gray
exit 1
