# Shared Windows cloudflared service / process helpers (PowerShell 5.1).

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

function Test-ScServiceExists([string]$Name) {
    if (-not $Name) { return $false }
    $result = Invoke-ScNative -ArgumentList @("query", $Name)
    return ($result.ExitCode -eq 0)
}

function Get-CloudflaredServiceNames {
  return @("Cloudflared", "cloudflared")
}

function Get-InstalledCloudflaredServiceName {
    foreach ($name in (Get-CloudflaredServiceNames)) {
        if (Test-ScServiceExists $name) { return $name }
    }
    return $null
}

function Stop-CloudflaredProcesses {
    Get-Process cloudflared -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
}

function Wait-ScServiceState {
    param(
        [string]$ServiceNameValue,
        [string[]]$DesiredStates,
        [int]$TimeoutSeconds = 20
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $result = Invoke-ScNative -ArgumentList @("query", $ServiceNameValue)
        if ($result.ExitCode -ne 0) { return $false }
        foreach ($state in $DesiredStates) {
            if ($result.Output -match "STATE\s+:\s+\d+\s+$state") {
                return $true
            }
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Stop-CloudflaredServiceSafe {
    param(
        [string]$ServiceNameValue,
        [int]$TimeoutSeconds = 20,
        [string]$CloudflaredExe = ""
    )
    if (-not $ServiceNameValue) { return $false }
    if (-not (Test-ScServiceExists $ServiceNameValue)) { return $true }

    $query = Invoke-ScNative -ArgumentList @("query", $ServiceNameValue)
    if ($query.Output -match "STATE\s+:\s+\d+\s+STOPPED") {
        return $true
    }

    Invoke-ScNative -ArgumentList @("stop", $ServiceNameValue) | Out-Null
    if (Wait-ScServiceState -ServiceNameValue $ServiceNameValue -DesiredStates @("STOPPED") -TimeoutSeconds $TimeoutSeconds) {
        return $true
    }

    Stop-CloudflaredProcesses
    Start-Sleep -Seconds 2
    if (Wait-ScServiceState -ServiceNameValue $ServiceNameValue -DesiredStates @("STOPPED") -TimeoutSeconds 10) {
        return $true
    }

    $query = Invoke-ScNative -ArgumentList @("query", $ServiceNameValue)
    if ($query.Output -match "STOP_PENDING" -and $CloudflaredExe -and (Test-Path $CloudflaredExe)) {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & $CloudflaredExe service uninstall 2>&1 | Out-Null
        } finally {
            $ErrorActionPreference = $prev
        }
        Start-Sleep -Seconds 2
        Stop-CloudflaredProcesses
        return -not (Test-ScServiceExists $ServiceNameValue)
    }

    return ($query.Output -match "STATE\s+:\s+\d+\s+STOPPED")
}

function Test-CloudflaredServiceRunning {
    param([string]$ServiceNameValue)
    if (-not $ServiceNameValue) { return $false }
    $result = Invoke-ScNative -ArgumentList @("query", $ServiceNameValue)
    return ($result.Output -match "STATE\s+:\s+\d+\s+RUNNING")
}

function Start-CloudflaredServiceSafe {
    param(
        [string]$ServiceNameValue,
        [int]$WarmupSeconds = 8
    )
    if (-not $ServiceNameValue) { return $false }
    if (-not (Test-ScServiceExists $ServiceNameValue)) { return $false }

    Invoke-ScNative -ArgumentList @("start", $ServiceNameValue) | Out-Null
    Start-Sleep -Seconds $WarmupSeconds
    $result = Invoke-ScNative -ArgumentList @("query", $ServiceNameValue)
    return ($result.Output -match "STATE\s+:\s+\d+\s+RUNNING")
}

function Restart-CloudflaredServiceSafe {
    param(
        [string]$ServiceNameValue,
        [int]$WarmupSeconds = 8,
        [string]$CloudflaredExe = ""
    )
    if (-not (Stop-CloudflaredServiceSafe -ServiceNameValue $ServiceNameValue -CloudflaredExe $CloudflaredExe)) {
        Stop-CloudflaredProcesses
    }
    if (-not (Test-ScServiceExists $ServiceNameValue)) {
        return $false
    }
    return (Start-CloudflaredServiceSafe -ServiceNameValue $ServiceNameValue -WarmupSeconds $WarmupSeconds)
}

function Set-CloudflaredServiceImagePath {
    param(
        [string]$ServiceNameValue,
        [string]$Exe,
        [string]$ConfigPath,
        [string]$TunnelNameValue
    )
    if (-not $ServiceNameValue) { throw "ServiceNameValue is required." }
    if (-not (Test-Path $Exe)) { throw "cloudflared.exe not found: $Exe" }
    if (-not (Test-Path $ConfigPath)) { throw "Config not found: $ConfigPath" }

    $imagePath = "`"$Exe`" --config `"$ConfigPath`" tunnel run $TunnelNameValue"
    $regPath = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceNameValue"
    if (-not (Test-Path $regPath)) {
        throw "Service registry key missing: $regPath"
    }
    Set-ItemProperty -Path $regPath -Name ImagePath -Value $imagePath
    return $imagePath
}

function Install-CloudflaredSystemProfileConfig {
    param(
        [string]$SourceConfigPath,
        [string]$CredentialsPath,
        [string]$PublicHostname,
        [int]$LocalPort = 8080
    )
    $destDir = "C:\Windows\System32\config\systemprofile\.cloudflared"
    New-Item -ItemType Directory -Force -Path $destDir | Out-Null

    $tunnelId = ((Get-Content $SourceConfigPath) | Where-Object { $_ -match '^\s*tunnel:\s*' } | Select-Object -First 1) -replace '^\s*tunnel:\s*', ''
    $tunnelId = $tunnelId.Trim()
    if (-not $tunnelId) { throw "Could not read tunnel id from $SourceConfigPath" }

    $destCred = Join-Path $destDir "$tunnelId.json"
    Copy-Item -Path $CredentialsPath -Destination $destCred -Force

    $destConfig = Join-Path $destDir "config.yml"
    @(
        "tunnel: $tunnelId",
        "credentials-file: $destCred",
        "ingress:",
        "  - hostname: $PublicHostname",
        "    service: http://127.0.0.1:$LocalPort",
        "  - service: http_status:404"
    ) | Set-Content -Path $destConfig -Encoding UTF8

    return @{
        ConfigPath = $destConfig
        CredentialsPath = $destCred
    }
}
