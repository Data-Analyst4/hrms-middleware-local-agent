param(
    [string]$TaskName = "HRMS-Middleware-Supervisor",
    [switch]$RemoveVenv,
    [switch]$RemoveFirewallRule
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$projectRoot = (Resolve-Path $PSScriptRoot).Path

Write-Host "== HRMS Middleware Uninstall ==" -ForegroundColor Cyan
Write-Host "Project: $projectRoot"
Write-Host ""

& (Join-Path $projectRoot "scripts\stop_stack.ps1") -TaskName $TaskName

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    if (-not (Test-IsAdmin)) {
        Write-Warning "Need Administrator to remove scheduled task. Re-run as Administrator or use remove_autostart.ps1."
    } else {
        & (Join-Path $projectRoot "scripts\remove_autostart.ps1") -TaskName $TaskName
    }
}

if (Test-IsAdmin) {
    $removeTunnel = Join-Path $projectRoot "scripts\remove_cloudflare_autostart.ps1"
    if (Test-Path $removeTunnel) {
        & $removeTunnel
    }
} else {
    Write-Warning "Skipped Cloudflare tunnel cleanup (Administrator required)."
}

if ($RemoveFirewallRule -and (Test-IsAdmin)) {
    foreach ($ruleName in @("HRMS Middleware Gateway 8000", "HRMS Middleware Gateway 8080")) {
        Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
        Write-Host "Removed firewall rule (if existed): $ruleName" -ForegroundColor Gray
    }
} elseif ($RemoveFirewallRule) {
    Write-Warning "Skipped firewall cleanup (Administrator required)."
}

if ($RemoveVenv) {
    $venv = Join-Path $projectRoot ".venv"
    if (Test-Path $venv) {
        Remove-Item -Recurse -Force $venv
        Write-Host "Removed virtual environment: $venv" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "Uninstall complete. Application files in $projectRoot were kept." -ForegroundColor Green
Write-Host "To fully remove, delete the project folder manually." -ForegroundColor Gray
