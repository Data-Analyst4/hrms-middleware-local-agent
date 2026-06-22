param(
    [string]$EnvFile = "configs/integration.local.env",
    [string]$LogFile = "var/logs/cloudflared.log",
    [switch]$StopOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

function Read-EnvFile {
    param([string]$Path)
    $vars = @{}
    if (-not (Test-Path $Path)) { return $vars }
    foreach ($line in Get-Content $Path) {
        $line = $line.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { continue }
        $key, $value = $line.Split("=", 2)
        $vars[$key.Trim()] = $value.Trim().Trim('"').Trim("'")
    }
    return $vars
}

$envVars = Read-EnvFile -Path (Join-Path $projectRoot $EnvFile)
$token = $envVars["CLOUDFLARE_TUNNEL_TOKEN"]
if (-not $token) { $token = $env:CLOUDFLARE_TUNNEL_TOKEN }
$publicHost = $envVars["CLOUDFLARE_PUBLIC_HOSTNAME"]
if (-not $publicHost) { $publicHost = "https://v8-mw.k95foods.com" }
$localPortRaw = $envVars["CLOUDFLARE_LOCAL_PORT"]
if (-not $localPortRaw) { $localPortRaw = "8080" }
$localPort = [int]$localPortRaw

$logDir = Split-Path (Join-Path $projectRoot $LogFile) -Parent
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logAbs = Join-Path $projectRoot $LogFile

$existing = Get-Process cloudflared -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Stopping existing cloudflared process(es)..."
    $existing | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

if ($StopOnly) {
    Write-Host "cloudflared stopped."
    exit 0
}

if (-not $token) {
    throw "CLOUDFLARE_TUNNEL_TOKEN not set. Add it to configs/integration.local.env"
}

$gatewayOk = $false
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$localPort/health" -UseBasicParsing -TimeoutSec 5
    $gatewayOk = ($r.StatusCode -eq 200)
} catch {
    Write-Warning "Local gateway not reachable on port $localPort. Start middleware first."
}

if (-not $gatewayOk) {
    throw "Middleware gateway must be running on http://127.0.0.1:$localPort before starting tunnel."
}

Write-Host "Starting Cloudflare tunnel -> http://127.0.0.1:$localPort"
Write-Host "Public hostname (expected): $publicHost"
Write-Host "Log: $logAbs"

$argLine = "tunnel run --token `"$token`""
Start-Process -FilePath "cloudflared.exe" `
    -ArgumentList $argLine `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $logAbs `
    -RedirectStandardError (Join-Path $logDir "cloudflared.err.log") | Out-Null

Start-Sleep -Seconds 8

$healthUrl = "$($publicHost.TrimEnd('/'))/health"
Write-Host "Testing $healthUrl ..."
try {
    $pub = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 20
    Write-Host "Public tunnel OK (HTTP $($pub.StatusCode))" -ForegroundColor Green
} catch {
    Write-Warning "Public health not reachable yet: $($_.Exception.Message)"
    Write-Host "If DNS fails for v8-mw.k95foods.com, add CNAME in Cloudflare DNS for that hostname,"
    Write-Host "or run START_TUNNEL_QUICK.cmd for a temporary trycloudflare.com URL."
    Write-Host "Check log: Get-Content '$logAbs' -Tail 30"
    if (Test-Path (Join-Path $logDir "cloudflared.err.log")) {
        Get-Content (Join-Path $logDir "cloudflared.err.log") -Tail 10
    }
}

# Register public URL on V8 device in middleware DB
$deviceId = "V8-T501-01"
$apiKey = "dev-middleware-key"
$patchBody = @{ middleware_public_url = $publicHost.TrimEnd('/') } | ConvertTo-Json -Compress
try {
    Invoke-RestMethod -Method Patch `
        -Uri "http://127.0.0.1:$localPort/api/v1/devices/$deviceId" `
        -Headers @{ "x-api-key" = $apiKey } `
        -ContentType "application/json" `
        -Body $patchBody | Out-Null
    Write-Host "Updated device $deviceId middleware_public_url -> $publicHost" -ForegroundColor Green
} catch {
    Write-Warning "Could not PATCH device registry: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "ERP team: ensure Branch V8 on dev.erp.k95foods.com has the same middleware URL: $publicHost"
