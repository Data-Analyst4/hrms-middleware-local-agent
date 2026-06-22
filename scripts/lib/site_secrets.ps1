# Per-site identity and secret helpers (one middleware PC = one machine = one ERP branch).

function New-SiteSecret {
    param([int]$Length = 43)
    $chars = (48..57) + (65..90) + (97..122)
    -join ($chars | Get-Random -Count $Length | ForEach-Object { [char]$_ })
}

function Get-SiteDeviceId {
    param(
        [string]$SiteCode,
        [string]$MachineLabel = "T501-01"
    )
    $code = ($SiteCode -replace '\s', '').ToUpperInvariant()
    if (-not $code) { throw "SiteCode is required." }
    return "$code-$MachineLabel"
}

function Get-SiteTunnelHostname {
    param([string]$SiteCode)
    $slug = ($SiteCode -replace '\s', '').ToLowerInvariant()
    if (-not $slug) { throw "SiteCode is required." }
    return "$slug-mw.k95foods.com"
}

function Get-SiteTunnelName {
    param([string]$SiteCode)
    $slug = ($SiteCode -replace '\s', '').ToLowerInvariant()
    return "$slug-middleware"
}

function Test-SitePlaceholderValue {
    param([string]$Value)
    if (-not $Value) { return $true }
    $v = $Value.Trim().Trim('"').Trim("'").ToLowerInvariant()
    return ($v -match '^change-me' -or $v -match '^replace-in' -or $v -eq 'dev-middleware-key' -or $v -eq 'your-')
}

function Set-YamlScalar {
    param(
        [string]$ConfigPath,
        [string]$Key,
        [string]$Value
    )
    if (-not (Test-Path $ConfigPath)) {
        throw "Config not found: $ConfigPath"
    }
    $escaped = $Value -replace '\\', '\\\\' -replace '"', '\"'
    $line = "${Key}: `"$escaped`""
    $lines = Get-Content $ConfigPath
    $out = @()
    $replaced = $false
    foreach ($l in $lines) {
        if ($l -match "^\s*$([regex]::Escape($Key))\s*:") {
            $out += $line
            $replaced = $true
        } else {
            $out += $l
        }
    }
    if (-not $replaced) { $out += $line }
    Set-Content -Path $ConfigPath -Value $out -Encoding UTF8
}

function Set-YamlScalarNumber {
    param(
        [string]$ConfigPath,
        [string]$Key,
        [string]$Value
    )
    $lines = Get-Content $ConfigPath
    $out = @()
    $replaced = $false
    foreach ($l in $lines) {
        if ($l -match "^\s*$([regex]::Escape($Key))\s*:") {
            $out += "${Key}: $Value"
            $replaced = $true
        } else {
            $out += $l
        }
    }
    if (-not $replaced) { $out += "${Key}: $Value" }
    Set-Content -Path $ConfigPath -Value $out -Encoding UTF8
}

function Write-K95VpsEnvSnippet {
    param(
        [string]$OutputPath,
        [string]$SiteCode,
        [string]$DeviceId,
        [string]$MiddlewareApiKey,
        [string]$WebhookSecret,
        [string]$TunnelHostname,
        [string]$ErpBaseUrl
    )
    $tunnelUrl = "https://$($TunnelHostname.TrimEnd('/'))"
    $erp = $ErpBaseUrl.TrimEnd('/')
    $slug = ($SiteCode -replace '\s', '').ToUpperInvariant()
    @"
# Paste into K95 ERP backend .env on VPS (Branch $slug)
# Then restart K95 backend. Must match configs/site.local.yaml on this PC.

# ERP -> this middleware PC (Import users, CRUD on machine)
MIDDLEWARE_API_KEY=$MiddlewareApiKey
${slug}_MIDDLEWARE_API_KEY=$MiddlewareApiKey

# This PC -> ERP attendance punches (HMAC)
${slug}_WEBHOOK_SECRET=$WebhookSecret

# Cloudflare tunnel to this PC
${slug}_TUNNEL_URL=$tunnelUrl
${slug}_DEVICE_ID=$DeviceId
MIDDLEWARE_BASE_URL=$tunnelUrl

# VPS-only: generate once with: openssl rand -hex 32
# MIDDLEWARE_ENCRYPTION_KEY=

# ERP punch endpoint (middleware uses this URL from site.local.yaml outbound_url)
# $erp/api/integrations/middleware/punch
"@ | Set-Content -Path $OutputPath -Encoding UTF8
}
