# Install Cloudflare tunnel to auto-start on boot and recover after crashes.
# Reads tunnel name/hostname from configs/site.local.yaml when not passed.
# Run as Administrator:
#   .\scripts\setup_cloudflare_autostart.ps1 -StartNow

param(
    [string]$TunnelName = "",
    [string]$PublicHostname = "",
    [int]$LocalPort = 0,
    [string]$SourceConfig = "",
    [string]$ServiceName = "cloudflared",
    [string]$WatchdogTaskName = "",
    [int]$BootDelaySeconds = 45,
    [switch]$StartNow,
    [switch]$SkipService,
    [switch]$SkipWatchdog
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib\project_paths.ps1")
. (Join-Path $PSScriptRoot "lib\cloudflared_windows.ps1")

$projectRoot = Get-ProjectRoot -ScriptRoot $PSScriptRoot
$siteCode = ((Read-SiteYamlValue -Key "outbound_site_code" -ProjectRoot $projectRoot -Default "SITE") -replace '\s', '').ToUpperInvariant()

if (-not $TunnelName) {
    $TunnelName = Read-SiteYamlValue -Key "cloudflare_tunnel_name" -Default "v8-middleware" -ProjectRoot $projectRoot
}
if (-not $PublicHostname) {
    $PublicHostname = Read-SiteYamlValue -Key "cloudflare_public_hostname" -Default "v8-mw.k95foods.com" -ProjectRoot $projectRoot
    $PublicHostname = $PublicHostname -replace '^https?://', '' -replace '/.*$', ''
}
if ($LocalPort -le 0) {
    $LocalPort = [int](Read-SiteYamlValue -Key "cloudflare_local_port" -Default "8080" -ProjectRoot $projectRoot)
}
if (-not $SourceConfig) {
    $SourceConfig = Join-Path $env:USERPROFILE ".cloudflared\config-$TunnelName.yml"
}
if (-not $WatchdogTaskName) {
    $WatchdogTaskName = "$siteCode-Cloudflare-Tunnel-Watchdog"
}

function Invoke-CloudflaredNative {
    param(
        [string]$Exe,
        [string[]]$ArgumentList
    )
    # cloudflared logs to stderr; do not let PS 5.1 treat that as a terminating error.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $lines = @()
    $exitCode = 0
    try {
        & $Exe @ArgumentList 2>&1 | ForEach-Object {
            $lines += $_.ToString()
        }
        if ($null -ne $LASTEXITCODE) {
            $exitCode = [int]$LASTEXITCODE
        }
    } finally {
        $ErrorActionPreference = $prev
    }
    return @{
        Output = ($lines -join [Environment]::NewLine)
        ExitCode = $exitCode
    }
}

function Test-ScServiceExists {
    param([string]$Name)
    if (-not $Name) { return $false }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        sc.exe query $Name 2>&1 | Out-Null
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Invoke-ScNative {
    param([string[]]$ArgumentList)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $lines = @()
    try {
        & sc.exe @ArgumentList 2>&1 | ForEach-Object { $lines += $_.ToString() }
        $exitCode = 0
        if ($null -ne $LASTEXITCODE) { $exitCode = [int]$LASTEXITCODE }
        return @{ Output = ($lines -join [Environment]::NewLine); ExitCode = $exitCode }
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Get-CloudflaredServiceName {
    param(
        [string]$PreferredName,
        [string]$InstallOutput = ""
    )
    foreach ($name in @($PreferredName, "Cloudflared", "cloudflared")) {
        if ($name -and (Test-ScServiceExists $name)) { return $name }
    }
    if ($InstallOutput -match 'windowsServiceName=(\S+)') {
        $parsed = $Matches[1].Trim()
        if (Test-ScServiceExists $parsed) { return $parsed }
        # Trust install log only when not a broken/partial registration.
        if ($InstallOutput -match 'service is installed' -and $InstallOutput -notmatch 'registry key already exists') {
            return $parsed
        }
    }
    $wmi = Get-CimInstance Win32_Service -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ieq 'cloudflared' -or $_.PathName -match 'cloudflared\.exe' } |
        Select-Object -First 1
    if ($wmi -and (Test-ScServiceExists $wmi.Name)) { return $wmi.Name }
    return $null
}

function Get-CloudflaredService {
    param(
        [string]$PreferredName,
        [string]$InstallOutput = ""
    )
    $name = Get-CloudflaredServiceName -PreferredName $PreferredName -InstallOutput $InstallOutput
    if (-not $name) { return $null }
    return Get-Service -Name $name -ErrorAction SilentlyContinue
}

function Start-CloudflaredServiceByName {
    param(
        [string]$ServiceNameValue,
        [switch]$Restart
    )
    if (-not $ServiceNameValue) { return $false }
    if ($Restart) {
        return (Restart-CloudflaredServiceSafe -ServiceNameValue $ServiceNameValue -WarmupSeconds 10 -CloudflaredExe $script:CloudflaredExeForService)
    }
    return (Start-CloudflaredServiceSafe -ServiceNameValue $ServiceNameValue -WarmupSeconds 10)
}

function Configure-CloudflaredWindowsService {
    param(
        [string]$ServiceNameValue,
        [string]$Exe,
        [string]$ConfigPath,
        [string]$CredentialsPath,
        [string]$TunnelNameValue,
        [string]$PublicHostnameValue,
        [int]$Port
    )
    Install-CloudflaredSystemProfileConfig `
        -SourceConfigPath $ConfigPath `
        -CredentialsPath $CredentialsPath `
        -PublicHostname $PublicHostnameValue `
        -LocalPort $Port | Out-Null
    $imagePath = Set-CloudflaredServiceImagePath `
        -ServiceNameValue $ServiceNameValue `
        -Exe $Exe `
        -ConfigPath $ConfigPath `
        -TunnelNameValue $TunnelNameValue
    Write-Host "Service command configured:" -ForegroundColor Green
    Write-Host "  $imagePath" -ForegroundColor DarkGray
}

function Wait-PublicTunnelHealthy {
    param(
        [string]$Hostname,
        [int]$Attempts = 15,
        [int]$SleepSeconds = 3
    )
    $url = "https://$($Hostname.TrimEnd('/'))/health"
    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 15
            if ($r.StatusCode -eq 200 -and $r.Content -match '"status"\s*:\s*"ok"') {
                return $true
            }
        } catch { }
        Start-Sleep -Seconds $SleepSeconds
    }
    return $false
}

function Repair-CloudflaredGhostRegistry {
    if (Test-ScServiceExists "Cloudflared") {
        return $false
    }
    $repairScript = Join-Path $PSScriptRoot "repair_cloudflare_registry.ps1"
    if (Test-Path $repairScript) {
        & $repairScript -Quiet | Out-Null
        return $true
    }
    return $false
}

function Register-CloudflaredRunnerTask {
    param(
        [string]$Exe,
        [string]$ConfigPath,
        [string]$TunnelNameValue,
        [string]$TaskName = "V8-Cloudflare-Tunnel-Runner",
        [int]$BootDelaySecondsValue = 45,
        [string]$ProjectRoot
    )
    $argLine = "tunnel --config `"$ConfigPath`" run $TunnelNameValue"
    $action = New-ScheduledTaskAction -Execute $Exe -Argument $argLine -WorkingDirectory $ProjectRoot
    $bootTrigger = New-ScheduledTaskTrigger -AtStartup
    if ($BootDelaySecondsValue -gt 0) {
        $bootTrigger.Delay = "PT${BootDelaySecondsValue}S"
    }
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1)
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $bootTrigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Runs cloudflared tunnel when Windows service install is unavailable." `
        -Force | Out-Null
    Write-Host "Tunnel runner task registered: $TaskName" -ForegroundColor Green
    return $TaskName
}

function Start-CloudflaredRunner {
    param(
        [string]$Exe,
        [string]$ConfigPath,
        [string]$TunnelNameValue,
        [string]$RunnerTaskName = "V8-Cloudflare-Tunnel-Runner"
    )
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    $task = Get-ScheduledTask -TaskName $RunnerTaskName -ErrorAction SilentlyContinue
    if ($task) {
        Start-ScheduledTask -TaskName $RunnerTaskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 5
        if (Get-Process cloudflared -ErrorAction SilentlyContinue) { return $true }
    }
    Start-Process -FilePath $Exe -ArgumentList @("tunnel", "--config", $ConfigPath, "run", $TunnelNameValue) `
        -WindowStyle Hidden -WorkingDirectory (Split-Path $Exe) | Out-Null
    Start-Sleep -Seconds 5
    return [bool](Get-Process cloudflared -ErrorAction SilentlyContinue)
}

function Ensure-CloudflaredWindowsService {
    param(
        [string]$Exe,
        [string]$ConfigPath,
        [string]$PreferredServiceName,
        [switch]$StartNowSwitch
    )

    $existingName = Get-CloudflaredServiceName -PreferredName $PreferredServiceName
    if ($existingName -and (Test-ScServiceExists $existingName)) {
        $existing = Get-Service -Name $existingName -ErrorAction SilentlyContinue
        Write-Host "cloudflared Windows service already present ($existingName)." -ForegroundColor Yellow
        Invoke-ScNative -ArgumentList @("config", $existingName, "start=", "auto") | Out-Null
        if ($StartNowSwitch) {
            Start-CloudflaredServiceByName -ServiceNameValue $existingName -Restart:($existing -and $existing.Status -eq "Running") | Out-Null
        }
        return $existingName
    }

    Repair-CloudflaredGhostRegistry | Out-Null

    Write-Host "Installing Windows service for tunnel '$TunnelName'..." -ForegroundColor Cyan
    $install = Invoke-CloudflaredNative -Exe $Exe -ArgumentList @("--config", $ConfigPath, "service", "install")
    if ($install.Output.Trim()) { Write-Host $install.Output.Trim() -ForegroundColor DarkGray }

    $serviceName = Get-CloudflaredServiceName -PreferredName $PreferredServiceName -InstallOutput $install.Output

    if (-not $serviceName -and $install.Output -match 'registry key already exists') {
        Write-Host "Repairing orphan registry and retrying service install..." -ForegroundColor Yellow
        Repair-CloudflaredGhostRegistry | Out-Null
        Invoke-CloudflaredNative -Exe $Exe -ArgumentList @("service", "uninstall") | Out-Null
        Start-Sleep -Seconds 2
        Repair-CloudflaredGhostRegistry | Out-Null
        $install = Invoke-CloudflaredNative -Exe $Exe -ArgumentList @("--config", $ConfigPath, "service", "install")
        if ($install.Output.Trim()) { Write-Host $install.Output.Trim() -ForegroundColor DarkGray }
        $serviceName = Get-CloudflaredServiceName -PreferredName $PreferredServiceName -InstallOutput $install.Output
    }

    if (-not $serviceName -or -not (Test-ScServiceExists $serviceName)) {
        Write-Warning "cloudflared Windows service could not be installed (exit $($install.ExitCode))."
        return $null
    }

    Invoke-ScNative -ArgumentList @("config", $serviceName, "start=", "auto") | Out-Null
    Write-Host "Service '$serviceName' set to Automatic start." -ForegroundColor Green
    if ($StartNowSwitch) {
        Start-CloudflaredServiceByName -ServiceNameValue $serviceName | Out-Null
    }
    return $serviceName
}

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Find-CloudflaredExe {
    $candidates = @(
        "C:\Program Files (x86)\cloudflared\cloudflared.exe",
        "C:\Program Files\cloudflared\cloudflared.exe",
        (Get-Command cloudflared.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
    ) | Where-Object { $_ -and (Test-Path $_) }
    if (-not $candidates) {
        throw "cloudflared.exe not found. Install from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
    }
    return $candidates[0]
}

function Stop-ManualCloudflared {
    Get-Process cloudflared -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "Stopping manual cloudflared pid=$($_.Id)" -ForegroundColor Yellow
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
}

function Install-ProgramDataConfig {
    param(
        [string]$SourceConfigPath,
        [string]$TunnelNameValue,
        [int]$Port
    )

    if (-not (Test-Path $SourceConfigPath)) {
        throw "Missing tunnel config: $SourceConfigPath"
    }

    $lines = Get-Content $SourceConfigPath
    $tunnelId = ($lines | Where-Object { $_ -match '^\s*tunnel:\s*' } | Select-Object -First 1) -replace '^\s*tunnel:\s*', ''
    $tunnelId = $tunnelId.Trim()
    # Config may list multiple UUIDs if tunnel was created repeatedly — use first credentials file that exists.
    $tunnelCandidates = @($tunnelId -split '\s+' | Where-Object { $_ -match '^[0-9a-fA-F-]{36}$' })
    if ($tunnelCandidates.Count -eq 0) {
        throw "Could not read tunnel id from $SourceConfigPath"
    }
    $userCred = $null
    foreach ($candidate in $tunnelCandidates) {
        $path = Join-Path $env:USERPROFILE ".cloudflared\$candidate.json"
        if (Test-Path $path) {
            $tunnelId = $candidate
            $userCred = $path
            break
        }
    }
    if (-not $userCred) {
        $tunnelId = $tunnelCandidates[0]
        $userCred = Join-Path $env:USERPROFILE ".cloudflared\$tunnelId.json"
    }
    if (-not (Test-Path $userCred)) {
        throw "Missing credentials file: $userCred"
    }

    $destDir = "C:\ProgramData\cloudflared"
    New-Item -ItemType Directory -Force -Path $destDir | Out-Null

    $destCred = Join-Path $destDir "$tunnelId.json"
    Copy-Item -Path $userCred -Destination $destCred -Force

    $destConfig = Join-Path $destDir "config.yml"
    @(
        "tunnel: $tunnelId",
        "credentials-file: $destCred",
        "ingress:",
        "  - hostname: $PublicHostname",
        "    service: http://127.0.0.1:$Port",
        "  - service: http_status:404"
    ) | Set-Content -Path $destConfig -Encoding UTF8

    return @{
        ConfigPath = $destConfig
        CredentialsPath = $destCred
        TunnelId = $tunnelId
    }
}

if (-not (Test-IsAdmin)) {
    throw "Run this script as Administrator (right-click PowerShell -> Run as administrator)."
}

$projectRoot = Get-ProjectRoot -ScriptRoot $PSScriptRoot
$cloudflaredExe = Find-CloudflaredExe
$script:CloudflaredExeForService = $cloudflaredExe
$logDir = Join-Path $projectRoot "var\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

Write-Host "Using cloudflared: $cloudflaredExe" -ForegroundColor Cyan
Write-Host "Public hostname: https://$PublicHostname" -ForegroundColor Cyan

$deployed = Install-ProgramDataConfig -SourceConfigPath $SourceConfig -TunnelNameValue $TunnelName -Port $LocalPort
Write-Host "Deployed config: $($deployed.ConfigPath)" -ForegroundColor Green

Stop-ManualCloudflared

$runnerTaskName = "$siteCode-Cloudflare-Tunnel-Runner"
$tunnelMode = "service"
$modeFile = Join-Path $projectRoot "var\logs\cloudflared-mode.txt"

if (-not $SkipService) {
    $resolvedServiceName = Ensure-CloudflaredWindowsService `
        -Exe $cloudflaredExe `
        -ConfigPath $deployed.ConfigPath `
        -PreferredServiceName $ServiceName `
        -StartNowSwitch:$false
    if ($resolvedServiceName) {
        $ServiceName = $resolvedServiceName
        $tunnelMode = "service"
        Configure-CloudflaredWindowsService `
            -ServiceNameValue $ServiceName `
            -Exe $cloudflaredExe `
            -ConfigPath $deployed.ConfigPath `
            -CredentialsPath $deployed.CredentialsPath `
            -TunnelNameValue $TunnelName `
            -PublicHostnameValue $PublicHostname `
            -Port $LocalPort
        if ($StartNow) {
            $serviceStarted = Restart-CloudflaredServiceSafe `
                -ServiceNameValue $ServiceName `
                -WarmupSeconds 12 `
                -CloudflaredExe $cloudflaredExe
            if (-not $serviceStarted -or -not (Test-CloudflaredServiceRunning -ServiceNameValue $ServiceName)) {
                Write-Warning "Windows service did not stay RUNNING; switching to scheduled-task runner."
                Invoke-CloudflaredNative -Exe $cloudflaredExe -ArgumentList @("service", "uninstall") | Out-Null
                Stop-CloudflaredProcesses
                $resolvedServiceName = $null
            }
        }
    }
    if (-not $resolvedServiceName -and $tunnelMode -eq "service") {
        Write-Host ""
        Write-Host "Falling back to scheduled-task tunnel runner (Windows service unavailable)." -ForegroundColor Yellow
        $runnerTaskName = Register-CloudflaredRunnerTask `
            -Exe $cloudflaredExe `
            -ConfigPath $deployed.ConfigPath `
            -TunnelNameValue $TunnelName `
            -BootDelaySecondsValue $BootDelaySeconds `
            -ProjectRoot $projectRoot
        $tunnelMode = "runner"
        if ($StartNow) {
            $ok = Start-CloudflaredRunner -Exe $cloudflaredExe -ConfigPath $deployed.ConfigPath -TunnelNameValue $TunnelName -RunnerTaskName $runnerTaskName
            if ($ok) {
                Write-Host "cloudflared tunnel process started." -ForegroundColor Green
            } else {
                Write-Warning "Could not verify cloudflared process started."
            }
        }
    }
}

Set-Content -Path $modeFile -Value $tunnelMode -Encoding ASCII

if (-not $SkipWatchdog) {
    $watchdogScript = Join-Path $projectRoot "scripts\ensure_cloudflare_tunnel.ps1"
    if (-not (Test-Path $watchdogScript)) {
        throw "Missing watchdog script: $watchdogScript"
    }

    $watchdogArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$watchdogScript`" -PublicHostname `"$PublicHostname`" -ServiceName `"$ServiceName`" -LocalPort $LocalPort -TunnelMode `"$tunnelMode`" -RunnerTaskName `"$runnerTaskName`""
    $bootAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $watchdogArgs -WorkingDirectory $projectRoot
    $bootTrigger = New-ScheduledTaskTrigger -AtStartup
    if ($BootDelaySeconds -gt 0) {
        $bootTrigger.Delay = "PT${BootDelaySeconds}S"
    }

    $repeatTrigger = New-ScheduledTaskTrigger `
        -Once `
        -At (Get-Date).Date `
        -RepetitionInterval (New-TimeSpan -Minutes 3) `
        -RepetitionDuration (New-TimeSpan -Days 3650)

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit ([TimeSpan]::Zero)

    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

    Register-ScheduledTask `
        -TaskName $WatchdogTaskName `
        -Action $bootAction `
        -Trigger @($bootTrigger, $repeatTrigger) `
        -Settings $settings `
        -Principal $principal `
        -Description "Ensures Cloudflare tunnel for $PublicHostname is running; restarts service if health check fails." `
        -Force | Out-Null

    Write-Host "Watchdog scheduled task created: $WatchdogTaskName (every 3 minutes + at boot)" -ForegroundColor Green
}

if ($StartNow) {
    if (Wait-PublicTunnelHealthy -Hostname $PublicHostname) {
        Write-Host "Public tunnel healthy: https://$PublicHostname/health" -ForegroundColor Green
    } else {
        Write-Host "Public tunnel not healthy yet; running watchdog recovery once..." -ForegroundColor Yellow
        & (Join-Path $projectRoot "scripts\ensure_cloudflare_tunnel.ps1") `
            -PublicHostname $PublicHostname `
            -ServiceName $ServiceName `
            -LocalPort $LocalPort `
            -TunnelMode $tunnelMode `
            -RunnerTaskName $runnerTaskName
    }
}

Write-Host ""
Write-Host "=== Cloudflare tunnel autostart configured ===" -ForegroundColor Green
Write-Host "  Mode:    $tunnelMode"
if ($tunnelMode -eq "service") {
    Write-Host "  Service: $ServiceName (Automatic)"
} else {
    Write-Host "  Runner:  $runnerTaskName (At startup)"
}
Write-Host "  Config:  $($deployed.ConfigPath)"
Write-Host "  URL:     https://$PublicHostname/health"
Write-Host ""
Write-Host "Verify:"
Write-Host "  Get-Service $ServiceName"
Write-Host "  curl.exe -s https://$PublicHostname/health"
Write-Host ""
Write-Host "Also run middleware autostart if not done:"
Write-Host "  .\scripts\setup_autostart.ps1 -StartNow"
