# Recreate missing Cloudflare tunnel credentials (.json) for this Windows user.
# Use when REPAIR_CLOUDFLARE fails with "Missing credentials file: ...json"
param(
    [switch]$Force,
    [switch]$SkipAutostart
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib\project_paths.ps1")

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Find-CloudflaredExePath {
    $candidates = @(
        "C:\Program Files (x86)\cloudflared\cloudflared.exe",
        "C:\Program Files\cloudflared\cloudflared.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "cloudflared not found. Install from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
}

function Invoke-CloudflaredLines {
    param([string[]]$Arguments)
    $exe = Find-CloudflaredExePath
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $lines = @(& $exe @Arguments 2>&1 | ForEach-Object { $_.ToString() })
        return @{ Exe = $exe; Lines = $lines; ExitCode = $(if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }) }
    } finally {
        $ErrorActionPreference = $prev
    }
}

if (-not (Test-IsAdmin)) {
    throw "Run as Administrator (use RECREATE_CLOUDFLARE_TUNNEL.cmd)."
}

$projectRoot = Get-ProjectRoot -ScriptRoot $PSScriptRoot
Set-Location $projectRoot

$tunnelName = Read-SiteYamlValue -Key "cloudflare_tunnel_name" -ProjectRoot $projectRoot -Default "v8-middleware"
$publicHost = (Read-SiteYamlValue -Key "cloudflare_public_hostname" -ProjectRoot $projectRoot -Default "v8-mw.k95foods.com") -replace '^https?://', '' -replace '/.*$', ''
$localPort = [int](Read-SiteYamlValue -Key "cloudflare_local_port" -ProjectRoot $projectRoot -Default "8080")
$configDir = Join-Path $env:USERPROFILE ".cloudflared"
$configPath = Join-Path $configDir "config-$tunnelName.yml"
$certPath = Join-Path $configDir "cert.pem"

Write-Host ""
Write-Host "== Repair Cloudflare tunnel credentials ==" -ForegroundColor Cyan
Write-Host "User profile: $env:USERPROFILE"
Write-Host "Tunnel:       $tunnelName"
Write-Host "Hostname:     $publicHost"
Write-Host ""

if (-not (Test-Path $certPath)) {
    Write-Host "ERROR: $certPath not found." -ForegroundColor Red
    Write-Host "Run first (same Admin user):" -ForegroundColor Yellow
    Write-Host "  cloudflared tunnel login" -ForegroundColor White
    Write-Host "Select k95foods.com in the browser, then run this script again." -ForegroundColor Yellow
    exit 1
}

$neededId = $null
if (Test-Path $configPath) {
    $tunnelLine = Get-Content $configPath | Where-Object { $_ -match '^\s*tunnel:\s*' } | Select-Object -First 1
    if ($tunnelLine) {
        $neededId = (($tunnelLine -replace '^\s*tunnel:\s*', '').Trim() -split '\s+' | Where-Object { $_ -match '^[0-9a-fA-F-]{36}$' } | Select-Object -First 1)
    }
}

$jsonFiles = @(Get-ChildItem -Path $configDir -Filter "*.json" -ErrorAction SilentlyContinue)
$credPath = $null
if ($neededId) {
    $credPath = Join-Path $configDir "$neededId.json"
}
if ($credPath -and (Test-Path $credPath)) {
    Write-Host "Credentials OK: $credPath" -ForegroundColor Green
    if (-not $SkipAutostart) {
        & (Join-Path $PSScriptRoot "repair_cloudflare_autostart.ps1") -StartNow
    }
    exit 0
}

Write-Host "Missing tunnel credentials (.json) in $configDir" -ForegroundColor Yellow
if ($neededId) {
    Write-Host "  Config expects: $neededId.json" -ForegroundColor Gray
}
if ($jsonFiles.Count -gt 0) {
    Write-Host "  Found other json files (wrong tunnel id?):" -ForegroundColor Gray
    $jsonFiles | ForEach-Object { Write-Host "    $($_.Name)" -ForegroundColor Gray }
}

Write-Host ""
Write-Host "Cloudflare does not re-issue lost .json files." -ForegroundColor Yellow
Write-Host "Options:" -ForegroundColor Yellow
Write-Host "  A) Copy the matching *.json from the OLD V8 PC into:" -ForegroundColor White
Write-Host "     $configDir" -ForegroundColor Gray
Write-Host "  B) Recreate tunnel on THIS PC (below) — needs -Force if tunnel exists remotely" -ForegroundColor White
Write-Host ""

if (-not $Force) {
    Write-Host "To recreate tunnel + new credentials on this PC, run:" -ForegroundColor Cyan
    Write-Host "  RECREATE_CLOUDFLARE_TUNNEL.cmd" -ForegroundColor White
    Write-Host "  (confirms delete of remote tunnel '$tunnelName' and creates a fresh one)" -ForegroundColor DarkGray
    exit 2
}

Write-Host "Recreating tunnel '$tunnelName'..." -ForegroundColor Cyan
$list = Invoke-CloudflaredLines -Arguments @("tunnel", "list", "--output", "json")
$exists = $false
if ($list.Lines -join "`n" -match $tunnelName) {
    $exists = $true
    Write-Host "Deleting existing remote tunnel '$tunnelName'..." -ForegroundColor Yellow
    $del = Invoke-CloudflaredLines -Arguments @("tunnel", "delete", $tunnelName)
    $del.Lines | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray }
}

Write-Host "Creating tunnel '$tunnelName' (writes new .json to $configDir)..." -ForegroundColor Cyan
$create = Invoke-CloudflaredLines -Arguments @("tunnel", "create", $tunnelName)
$create.Lines | ForEach-Object { Write-Host $_ }

$newJson = @(Get-ChildItem -Path $configDir -Filter "*.json" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
if ($newJson.Count -eq 0) {
    throw "tunnel create did not write a .json file under $configDir"
}
Write-Host "Credentials created: $($newJson[0].FullName)" -ForegroundColor Green

& (Join-Path $PSScriptRoot "setup_cloudflare_tunnel.ps1") `
    -TunnelName $tunnelName `
    -PublicHostname $publicHost `
    -LocalPort $localPort

if (-not $SkipAutostart) {
    & (Join-Path $PSScriptRoot "repair_cloudflare_autostart.ps1") -StartNow
}

Write-Host ""
Write-Host "Done. Test:" -ForegroundColor Green
Write-Host "  curl.exe https://$publicHost/health" -ForegroundColor White
exit 0
