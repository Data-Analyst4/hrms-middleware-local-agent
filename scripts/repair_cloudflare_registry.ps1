# Remove orphan Cloudflared registry keys when Windows service is missing (Admin required).
param([switch]$Quiet)

$ErrorActionPreference = "Stop"

function Test-ScServiceExists([string]$Name) {
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

function ConvertTo-RegistryPsPath([string]$RegPath) {
    if ($RegPath -match '^HKLM\\(.+)$') {
        return "HKLM:\$($Matches[1])"
    }
    return $RegPath
}

function Remove-RegKeyIfPresent([string]$RegPath) {
    $psPath = ConvertTo-RegistryPsPath $RegPath
    if (-not (Test-Path -LiteralPath $psPath)) {
        return $false
    }
    Remove-Item -LiteralPath $psPath -Recurse -Force -ErrorAction Stop
    return -not (Test-Path -LiteralPath $psPath)
}

$serviceOk = Test-ScServiceExists "Cloudflared"
$removed = @()

if (-not $serviceOk) {
    foreach ($path in @(
            "HKLM\SYSTEM\CurrentControlSet\Services\EventLog\Application\Cloudflared",
            "HKLM\SYSTEM\CurrentControlSet\Services\Cloudflared"
        )) {
        if (Remove-RegKeyIfPresent $path) {
            $removed += $path
        }
    }
}

if (-not $Quiet) {
    if ($serviceOk) {
        Write-Host "Cloudflared Windows service is installed; no registry repair needed." -ForegroundColor Green
    } elseif ($removed.Count -gt 0) {
        Write-Host "Removed orphan registry keys:" -ForegroundColor Green
        $removed | ForEach-Object { Write-Host "  $_" }
    } else {
        Write-Host "No orphan Cloudflared registry keys found (already clean)." -ForegroundColor Yellow
    }
}
