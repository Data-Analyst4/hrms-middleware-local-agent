# Install cloudflared + register tunnel autostart (called from INSTALL_ONE_CLICK.ps1).
param(
    [string]$TunnelName = "",
    [string]$PublicHostname = "",
    [int]$LocalPort = 0,
    [switch]$StartNow,
    [switch]$SkipWingetInstall
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib\project_paths.ps1")
$projectRoot = Get-ProjectRoot -ScriptRoot $PSScriptRoot

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
function Write-Step([string]$Message) {
    Write-Host $Message -ForegroundColor Cyan
}

function Install-CloudflaredPackage {
    if ($SkipWingetInstall) { return }
    if (Get-Command cloudflared.exe -ErrorAction SilentlyContinue) {
        Write-Host "cloudflared already installed." -ForegroundColor Green
        return
    }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Warning "winget not available; install cloudflared manually."
        return
    }
    Write-Step "Installing cloudflared..."
    & winget install --id Cloudflare.cloudflared -e --silent --disable-interactivity `
        --accept-package-agreements --accept-source-agreements --force
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "winget cloudflared install returned $LASTEXITCODE (may already be installed)."
    }
}

function Test-TunnelCredentialsPresent {
    $userConfig = Join-Path $env:USERPROFILE ".cloudflared\config-v8-middleware.yml"
    if (Test-Path $userConfig) { return $true }
    $cert = Join-Path $env:USERPROFILE ".cloudflared\cert.pem"
    return (Test-Path $cert)
}

Install-CloudflaredPackage

if (-not (Test-TunnelCredentialsPresent)) {
    Write-Warning @"
Cloudflare tunnel not configured on this PC yet.
After install, on a factory PC either:
  1) Copy folder $env:USERPROFILE\.cloudflared from an existing V8 site PC, then re-run INSTALL_ONE_CLICK.cmd
  2) Run: cloudflared tunnel login
     Then: .\scripts\setup_cloudflare_tunnel.ps1 -TunnelName $TunnelName -PublicHostname $PublicHostname
     Then: .\scripts\setup_cloudflare_autostart.ps1 -StartNow
"@
    return
}

$userConfig = Join-Path $env:USERPROFILE ".cloudflared\config-v8-middleware.yml"
if (-not (Test-Path $userConfig)) {
    $setupTunnel = Join-Path $projectRoot "scripts\setup_cloudflare_tunnel.ps1"
    if (Test-Path $setupTunnel) {
        Write-Step "Creating tunnel DNS route ($PublicHostname)..."
        & $setupTunnel -TunnelName $TunnelName -PublicHostname $PublicHostname -LocalPort $LocalPort
    }
}

$setupAuto = Join-Path $projectRoot "scripts\setup_cloudflare_autostart.ps1"
if (-not (Test-Path $setupAuto)) {
    Write-Warning "Missing $setupAuto"
    return
}

Write-Step "Registering Cloudflare tunnel autostart (service + watchdog)..."
& $setupAuto -TunnelName $TunnelName -PublicHostname $PublicHostname -LocalPort $LocalPort -StartNow:$StartNow
