# Re-apply Cloudflare tunnel autostart using values from configs/site.local.yaml.
param([switch]$StartNow)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib\project_paths.ps1")

$projectRoot = Get-ProjectRoot -ScriptRoot $PSScriptRoot
$siteCode = ((Read-SiteYamlValue -Key "outbound_site_code" -ProjectRoot $projectRoot -Default "SITE") -replace '\s', '').ToUpperInvariant()
$tunnelName = Read-SiteYamlValue -Key "cloudflare_tunnel_name" -ProjectRoot $projectRoot -Default "v8-middleware"
$publicHost = Read-SiteYamlValue -Key "cloudflare_public_hostname" -ProjectRoot $projectRoot -Default "v8-mw.k95foods.com"
$publicHost = $publicHost -replace '^https?://', '' -replace '/.*$', ''
$localPort = [int](Read-SiteYamlValue -Key "cloudflare_local_port" -ProjectRoot $projectRoot -Default "8080")
$sourceConfig = Join-Path $env:USERPROFILE ".cloudflared\config-$tunnelName.yml"
$watchdogTask = "$siteCode-Cloudflare-Tunnel-Watchdog"

Write-Host ""
Write-Host "Site:  $siteCode" -ForegroundColor Cyan
Write-Host "Tunnel: $tunnelName" -ForegroundColor Cyan
Write-Host "URL:    https://$publicHost" -ForegroundColor Cyan
Write-Host "Config: $sourceConfig" -ForegroundColor Gray
Write-Host ""

if (-not (Test-Path $sourceConfig)) {
    Write-Host "ERROR: Tunnel config not found." -ForegroundColor Red
    Write-Host "Run first:" -ForegroundColor Yellow
    Write-Host "  cloudflared tunnel login" -ForegroundColor White
    Write-Host "  powershell -ExecutionPolicy Bypass -File `"$projectRoot\scripts\setup_cloudflare_tunnel.ps1`" ``" -ForegroundColor White
    Write-Host "    -TunnelName `"$tunnelName`" -PublicHostname `"$publicHost`" -LocalPort $localPort" -ForegroundColor White
    exit 1
}

$setup = Join-Path $PSScriptRoot "setup_cloudflare_autostart.ps1"
$params = @{
    TunnelName       = $tunnelName
    PublicHostname   = $publicHost
    LocalPort        = $localPort
    SourceConfig     = $sourceConfig
    WatchdogTaskName = $watchdogTask
}
if ($StartNow) { $params.StartNow = $true }

& $setup @params
