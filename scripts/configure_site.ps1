param(
    [switch]$OpenEditor,
    [switch]$ForceFromExample,
    [string]$SiteCode = "",
    [string]$SiteName = "",
    [string]$MachineIp = "",
    [int]$MachineNumber = 0,
    [string]$ErpBaseUrl = "https://dev.erp.k95foods.com",
    [switch]$SkipPrompts,
    [switch]$RegenerateKeys
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib\project_paths.ps1")
. (Join-Path $PSScriptRoot "lib\site_secrets.ps1")

$projectRoot = Get-ProjectRoot -ScriptRoot $PSScriptRoot
Set-Location $projectRoot

Write-Host ""
Write-Host "== Configure Site PC (one machine + one middleware) ==" -ForegroundColor Cyan
Write-Host "Project: $projectRoot"
Write-Host ""

$created = Ensure-SiteLocalConfig -ProjectRoot $projectRoot -ForceFromExample:$ForceFromExample
$sitePath = Get-SiteLocalConfigPath -ProjectRoot $projectRoot

if (-not $SkipPrompts) {
    Write-Host "Enter site details (unique per factory PC)." -ForegroundColor Yellow
    Write-Host "Examples: site code V8, V9, PLANT-A" -ForegroundColor DarkGray
    Write-Host ""

    if (-not $SiteCode) {
        $current = Read-SiteYamlValue -Key "outbound_site_code" -ProjectRoot $projectRoot
        $prompt = "ERP branch / site code"
        if ($current) { $prompt += " [$current]" }
        $SiteCode = Read-Host $prompt
        if (-not $SiteCode) { $SiteCode = $current }
    }
    if (-not $SiteName) {
        $current = Read-SiteYamlValue -Key "site_name" -ProjectRoot $projectRoot
        $prompt = "PC label (site_name)"
        if ($current) { $prompt += " [$current]" }
        $SiteName = Read-Host $prompt
        if (-not $SiteName) { $SiteName = $current }
    }
    if (-not $MachineIp) {
        $current = Read-SiteYamlValue -Key "machine_sync_ip" -ProjectRoot $projectRoot
        $prompt = "Biometric machine LAN IP"
        if ($current) { $prompt += " [$current]" }
        $MachineIp = Read-Host $prompt
        if (-not $MachineIp) { $MachineIp = $current }
    }
    if ($MachineNumber -le 0) {
        $current = Read-SiteYamlValue -Key "machine_sync_machine_number" -ProjectRoot $projectRoot -Default "1"
        $raw = Read-Host "Machine STN number on device [$current]"
        if ($raw) { $MachineNumber = [int]$raw } else { $MachineNumber = [int]$current }
    }
    $erpPrompt = "K95 ERP base URL [$ErpBaseUrl]"
    $erpIn = Read-Host $erpPrompt
    if ($erpIn) { $ErpBaseUrl = $erpIn.TrimEnd('/') }
}

if (-not $SiteCode) {
    $SiteCode = Read-SiteYamlValue -Key "outbound_site_code" -ProjectRoot $projectRoot -Default "V8"
}
if (-not $SiteName) {
    $SiteName = Read-SiteYamlValue -Key "site_name" -ProjectRoot $projectRoot -Default "Factory Gate PC"
}
if (-not $MachineIp) {
    $MachineIp = Read-SiteYamlValue -Key "machine_sync_ip" -ProjectRoot $projectRoot -Default "192.168.1.100"
}
if ($MachineNumber -le 0) {
    $MachineNumber = [int](Read-SiteYamlValue -Key "machine_sync_machine_number" -ProjectRoot $projectRoot -Default "1")
}

$deviceId = Get-SiteDeviceId -SiteCode $SiteCode
$tunnelHost = Get-SiteTunnelHostname -SiteCode $SiteCode
$tunnelName = Get-SiteTunnelName -SiteCode $SiteCode
$punchUrl = "$($ErpBaseUrl.TrimEnd('/'))/api/integrations/middleware/punch"

$middlewareKey = Read-SiteYamlValue -Key "middleware_api_key" -ProjectRoot $projectRoot
$webhookSecret = Read-SiteYamlValue -Key "outbound_hmac_secret" -ProjectRoot $projectRoot
if ($RegenerateKeys -or (Test-SitePlaceholderValue $middlewareKey)) {
    $middlewareKey = New-SiteSecret
    Write-Host "Generated new middleware_api_key for site $SiteCode" -ForegroundColor Green
}
if ($RegenerateKeys -or (Test-SitePlaceholderValue $webhookSecret)) {
    $webhookSecret = New-SiteSecret
    Write-Host "Generated new outbound_hmac_secret for site $SiteCode" -ForegroundColor Green
}

Set-YamlScalar -ConfigPath $sitePath -Key "site_name" -Value $SiteName
Set-YamlScalar -ConfigPath $sitePath -Key "outbound_site_code" -Value $SiteCode.ToUpperInvariant()
Set-YamlScalar -ConfigPath $sitePath -Key "outbound_device_id" -Value $deviceId
Set-YamlScalar -ConfigPath $sitePath -Key "machine_sync_ip" -Value $MachineIp
Set-YamlScalarNumber -ConfigPath $sitePath -Key "machine_sync_machine_number" -Value "$MachineNumber"
Set-YamlScalar -ConfigPath $sitePath -Key "device_lan_ip_for_firewall" -Value $MachineIp
Set-YamlScalar -ConfigPath $sitePath -Key "middleware_api_key" -Value $middlewareKey
Set-YamlScalar -ConfigPath $sitePath -Key "outbound_hmac_secret" -Value $webhookSecret
Set-YamlScalar -ConfigPath $sitePath -Key "outbound_url" -Value $punchUrl
$factoryPath = Get-FactoryConfigPath -ProjectRoot $projectRoot
$outboundApiKey = Read-YamlScalar -ConfigPath $sitePath -Key "outbound_api_key" -Default ""
if (Test-SitePlaceholderValue $outboundApiKey) {
    $factoryApiKey = Read-YamlScalar -ConfigPath $factoryPath -Key "outbound_api_key" -Default ""
    if ($factoryApiKey -and -not (Test-SitePlaceholderValue $factoryApiKey)) {
        Set-YamlScalar -ConfigPath $sitePath -Key "outbound_api_key" -Value $factoryApiKey
        Write-Host "Set outbound_api_key from factory.yaml (ERP punch API key)." -ForegroundColor Gray
    } else {
        Write-Host "WARNING: Ask DevOps for K95 outbound_api_key and add to site.local.yaml." -ForegroundColor Yellow
    }
}
Set-YamlScalar -ConfigPath $sitePath -Key "cloudflare_public_hostname" -Value $tunnelHost
Set-YamlScalar -ConfigPath $sitePath -Key "cloudflare_tunnel_name" -Value $tunnelName

$snippetPath = Join-Path $projectRoot "configs\k95-vps-snippet.env"
Write-K95VpsEnvSnippet `
    -OutputPath $snippetPath `
    -SiteCode $SiteCode.ToUpperInvariant() `
    -DeviceId $deviceId `
    -MiddlewareApiKey $middlewareKey `
    -WebhookSecret $webhookSecret `
    -TunnelHostname $tunnelHost `
    -ErpBaseUrl $ErpBaseUrl

Write-Host ""
Write-Host "=== Site configured ===" -ForegroundColor Green
Write-Host "  site_code:     $($SiteCode.ToUpperInvariant())"
Write-Host "  device_id:     $deviceId"
Write-Host "  machine IP:    $MachineIp (STN $MachineNumber)"
Write-Host "  tunnel:        https://$tunnelHost"
Write-Host "  punch URL:     $punchUrl"
Write-Host ""
Write-Host "K95 VPS env snippet (give to DevOps):" -ForegroundColor Cyan
Write-Host "  $snippetPath"
Write-Host ""
Get-Content $snippetPath | Write-Host
Write-Host ""

$dllRel = Read-SiteYamlValue -Key "machine_sdk_dll_path" -ProjectRoot $projectRoot
$dllAbs = Join-Path $projectRoot ($dllRel -replace '/', '\')
if (Test-Path $dllAbs) {
    Write-Host "SDK DLL: OK ($dllRel)" -ForegroundColor Green
} else {
    Write-Host "SDK DLL missing: $dllAbs" -ForegroundColor Red
}

if ($OpenEditor -or $created) {
    Write-Host "Opening site.local.yaml..." -ForegroundColor Cyan
    Start-Process notepad.exe -ArgumentList $sitePath
}

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1) DevOps: paste configs/k95-vps-snippet.env into K95 VPS .env and restart backend"
Write-Host "  2) This PC: run 2-INSTALL_FACTORY.cmd as Administrator"
Write-Host "  3) Test punches: .\.venv\Scripts\python.exe scripts\_probe_erp_punch.py"
Write-Host ""
