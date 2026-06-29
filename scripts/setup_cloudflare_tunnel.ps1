# Cloudflare Tunnel setup for middleware HRMS APIs (one tunnel per site PC).
# Prerequisites: cloudflared installed and authenticated (cloudflared tunnel login).

param(
    [Parameter(Mandatory = $true)][string]$TunnelName,
    [Parameter(Mandatory = $true)][string]$PublicHostname,
    [int]$LocalPort = 8080,
    [string]$ConfigDir = "$env:USERPROFILE\.cloudflared"
)

$ErrorActionPreference = "Stop"

function Invoke-Cloudflared {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    # cloudflared logs warnings to stderr; PowerShell must not treat them as fatal errors.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $lines = @(& cloudflared @Arguments 2>&1)
    } finally {
        $ErrorActionPreference = $prev
    }
    return @($lines | Where-Object {
        $_ -is [string] -and $_.Trim() -and $_ -notmatch '^\{"level":"warn"'
    })
}

function Get-CloudflaredTunnelJson {
    $text = (Invoke-Cloudflared -Arguments @("tunnel", "list", "--output", "json") | Out-String).Trim()
    if (-not $text) { return @() }
    return @($text | ConvertFrom-Json)
}

if (-not (Test-Path $ConfigDir)) {
    New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
}

$certPath = Join-Path $ConfigDir "cert.pem"
if (-not (Test-Path $certPath)) {
    Write-Host "Cloudflare login required (cert.pem not found)." -ForegroundColor Yellow
    Write-Host "Run: cloudflared tunnel login" -ForegroundColor Cyan
    Write-Host "Then select k95foods.com in the browser and click Authorize." -ForegroundColor Yellow
    exit 1
}

$existing = Get-CloudflaredTunnelJson | Where-Object { $_.name -eq $TunnelName } | Select-Object -First 1
if ($existing) {
    Write-Host "Tunnel '$TunnelName' already exists (id=$($existing.id))." -ForegroundColor Yellow
} else {
    Write-Host "Creating tunnel '$TunnelName'..."
    Invoke-Cloudflared -Arguments @("tunnel", "create", $TunnelName) | Out-Host
}

$TunnelId = (Get-CloudflaredTunnelJson | Where-Object { $_.name -eq $TunnelName } | Select-Object -First 1).id
if (-not $TunnelId) {
    throw "Could not resolve tunnel id for $TunnelName"
}

$configPath = Join-Path $ConfigDir "config-$TunnelName.yml"
$credentialsPath = Join-Path $ConfigDir "$TunnelId.json"
@(
    "tunnel: $TunnelId",
    "credentials-file: $credentialsPath",
    "ingress:",
    "  - hostname: $PublicHostname",
    "    service: http://127.0.0.1:$LocalPort",
    "  - service: http_status:404"
) | Set-Content -Path $configPath -Encoding UTF8

Write-Host "Route DNS $PublicHostname -> tunnel $TunnelName"
Invoke-Cloudflared -Arguments @("tunnel", "route", "dns", $TunnelName, $PublicHostname) | Out-Host

Write-Host ""
Write-Host "Config written: $configPath"
Write-Host "Run tunnel:"
Write-Host ('  cloudflared tunnel --config "' + $configPath + '" run ' + $TunnelName)
Write-Host ""
Write-Host "Set ERP branch middleware_tunnel_url to: https://$PublicHostname"
