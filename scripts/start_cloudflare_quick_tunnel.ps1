param(
    [int]$LocalPort = 8080,
    [string]$LogFile = "var/logs/cloudflared-quick.log",
    [int]$WaitSeconds = 15
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

$logAbs = Join-Path $projectRoot $LogFile
$logDir = Split-Path $logAbs -Parent
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

if (-not (Test-Path "http://127.0.0.1:$LocalPort/health")) {
    try {
        $h = Invoke-WebRequest -Uri "http://127.0.0.1:$LocalPort/health" -UseBasicParsing -TimeoutSec 5
        if ($h.StatusCode -ne 200) { throw "bad status" }
    } catch {
        throw "Middleware must be running on port $LocalPort first."
    }
}

Remove-Item $logAbs -Force -ErrorAction SilentlyContinue
$proc = Start-Process -FilePath "cloudflared.exe" `
    -ArgumentList "tunnel --url http://127.0.0.1:$LocalPort" `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -PassThru `
    -RedirectStandardOutput $logAbs `
    -RedirectStandardError (Join-Path $logDir "cloudflared-quick.err.log")

Start-Sleep -Seconds $WaitSeconds
$logText = ""
if (Test-Path $logAbs) { $logText = Get-Content $logAbs -Raw }
if (-not $logText -and (Test-Path (Join-Path $logDir "cloudflared-quick.err.log"))) {
    $logText = Get-Content (Join-Path $logDir "cloudflared-quick.err.log") -Raw
}

$url = $null
if ($logText -match '(https://[a-z0-9-]+\.trycloudflare\.com)') {
    $url = $Matches[1]
}

if (-not $url) {
    Write-Warning "Could not detect trycloudflare URL yet. Log tail:"
    Get-Content $logAbs -Tail 20 -ErrorAction SilentlyContinue
    exit 1
}

Write-Host "Quick tunnel URL: $url" -ForegroundColor Green

$deviceId = "V8-T501-01"
$apiKey = "dev-middleware-key"
$patchBody = @{ middleware_public_url = $url } | ConvertTo-Json -Compress
try {
    Invoke-RestMethod -Method Patch `
        -Uri "http://127.0.0.1:$LocalPort/api/v1/devices/$deviceId" `
        -Headers @{ "x-api-key" = $apiKey } `
        -ContentType "application/json" `
        -Body $patchBody | Out-Null
    Write-Host "Updated $deviceId middleware_public_url" -ForegroundColor Green
} catch {
    Write-Warning "PATCH device failed: $($_.Exception.Message)"
}

try {
    $pub = Invoke-WebRequest -Uri "$url/health" -UseBasicParsing -TimeoutSec 20
    Write-Host "Public health OK: HTTP $($pub.StatusCode)" -ForegroundColor Green
} catch {
    Write-Warning "Public health check failed: $($_.Exception.Message)"
}

$urlFile = Join-Path $projectRoot "var\logs\cloudflared-public-url.txt"
Set-Content -Path $urlFile -Value $url -Encoding UTF8NoBOM

function Update-K95BranchTunnelUrl {
    param([string]$PublicUrl)
    $envFile = Join-Path $projectRoot "configs\integration.local.env"
    if (-not (Test-Path $envFile)) { return }
    $vars = @{}
    foreach ($line in Get-Content $envFile) {
        $line = $line.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { continue }
        $k, $v = $line.Split("=", 2)
        $vars[$k.Trim()] = $v.Trim()
    }
    $k95Base = $vars["K95_BASE_URL"]
    $email = $vars["K95_INTEGRATION_EMAIL"]
    $password = $vars["K95_INTEGRATION_PASSWORD"]
    if (-not $k95Base -or -not $email -or -not $password) { return }

  $loginBody = @{ email = $email; password = $password } | ConvertTo-Json -Compress
    $login = Invoke-RestMethod -Method Post -Uri "$k95Base/api/auth/login" -ContentType "application/json" -Body $loginBody
    $token = $login.token
    if (-not $token) { $token = $login.accessToken }
    if (-not $token) { throw "K95 login succeeded but no token returned." }

    $branches = Invoke-RestMethod -Method Get -Uri "$k95Base/api/entities/Branch" -Headers @{ Authorization = "Bearer $token" }
    $v8 = $branches | Where-Object { $_.branch_name -eq "V8" } | Select-Object -First 1
    if (-not $v8) { throw "Branch V8 not found on K95 ERP." }

    $patchBody = @{ middleware_tunnel_url = $PublicUrl } | ConvertTo-Json -Compress
    Invoke-RestMethod -Method Patch `
        -Uri "$k95Base/api/entities/Branch/$($v8.id)" `
        -Headers @{ Authorization = "Bearer $token" } `
        -ContentType "application/json" `
        -Body $patchBody | Out-Null
    Write-Host "Updated K95 Branch V8 middleware_tunnel_url -> $PublicUrl" -ForegroundColor Green
}

try {
    Update-K95BranchTunnelUrl -PublicUrl $url
} catch {
    Write-Warning "Could not auto-update K95 Branch V8 URL: $($_.Exception.Message)"
    Write-Host "Manually set Branch V8 middleware_tunnel_url in ERP to: $url"
}

Write-Host ""
Write-Host "Saved URL: $urlFile"
Write-Host "cloudflared pid: $($proc.Id) (stops when process ends or PC reboots)"
