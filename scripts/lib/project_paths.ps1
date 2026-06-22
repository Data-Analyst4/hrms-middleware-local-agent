# Shared helpers for portable installs (any folder path, Windows 10+).
# Dot-source from scripts: . (Join-Path $PSScriptRoot "lib\project_paths.ps1")

function Get-ProjectRoot {
    param([string]$ScriptRoot = $PSScriptRoot)
    if ($ScriptRoot -match '[\\/]scripts$') {
        return (Resolve-Path (Join-Path $ScriptRoot "..")).Path
    }
    return (Resolve-Path $ScriptRoot).Path
}

function Get-SiteLocalConfigPath {
    param([string]$ProjectRoot = (Get-ProjectRoot))
    return Join-Path $ProjectRoot "configs\site.local.yaml"
}

function Get-SiteLocalExamplePath {
    param([string]$ProjectRoot = (Get-ProjectRoot))
    return Join-Path $ProjectRoot "configs\site.local.yaml.example"
}

function Get-FactoryConfigPath {
    param([string]$ProjectRoot = (Get-ProjectRoot))
    return Join-Path $ProjectRoot "configs\factory.yaml"
}

function Get-VenvPython {
    param([string]$ProjectRoot = (Get-ProjectRoot))
    return Join-Path $ProjectRoot ".venv\Scripts\python.exe"
}

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-IsWindows10OrLater {
    return ([System.Environment]::OSVersion.Version.Major -ge 10)
}

function Read-YamlScalar {
    param(
        [string]$ConfigPath,
        [string]$Key,
        [string]$Default = ""
    )
    if (-not (Test-Path $ConfigPath)) { return $Default }
    $content = Get-Content -Raw $ConfigPath
    $pattern = "(?m)^\s*$([regex]::Escape($Key))\s*:\s*(.+?)\s*$"
    if ($content -match $pattern) {
        return $Matches[1].Trim().Trim('"').Trim("'")
    }
    return $Default
}

function Read-SiteYamlValue {
    param(
        [string]$Key,
        [string]$Default = "",
        [string]$ProjectRoot = (Get-ProjectRoot)
    )
    $sitePath = Get-SiteLocalConfigPath -ProjectRoot $ProjectRoot
    $factoryPath = Get-FactoryConfigPath -ProjectRoot $ProjectRoot
    $fromSite = Read-YamlScalar -ConfigPath $sitePath -Key $Key -Default ""
    if ($fromSite) { return $fromSite }
    return Read-YamlScalar -ConfigPath $factoryPath -Key $Key -Default $Default
}

function Ensure-SiteLocalConfig {
    param(
        [string]$ProjectRoot = (Get-ProjectRoot),
        [switch]$ForceFromExample
    )
    $sitePath = Get-SiteLocalConfigPath -ProjectRoot $ProjectRoot
    $examplePath = Get-SiteLocalExamplePath -ProjectRoot $ProjectRoot
    if (-not (Test-Path $examplePath)) {
        throw "Missing template: $examplePath"
    }
    if (-not (Test-Path $sitePath) -or $ForceFromExample) {
        Copy-Item -Path $examplePath -Destination $sitePath -Force
        Write-Host "Created per-PC config: $sitePath" -ForegroundColor Green
        return $true
    }
    return $false
}

function Resolve-ConfigPath {
    param(
        [string]$Config,
        [string]$ProjectRoot = (Get-ProjectRoot)
    )
    if ([System.IO.Path]::IsPathRooted($Config)) {
        return $Config
    }
    return (Resolve-Path (Join-Path $ProjectRoot $Config) -ErrorAction Stop).Path
}

function Get-ActiveConfigRelative {
    # factory.yaml is the base; site.local.yaml is merged at runtime by Python.
    return "configs/factory.yaml"
}

function Show-SiteConfigChecklist {
    param([string]$ProjectRoot = (Get-ProjectRoot))
    $sitePath = Get-SiteLocalConfigPath -ProjectRoot $ProjectRoot
    Write-Host ""
    Write-Host "Per-site file (one PC = one machine): $sitePath" -ForegroundColor Cyan
    Write-Host "Required per factory site:" -ForegroundColor Yellow
    Write-Host "  outbound_site_code       - ERP branch code (V8, V9, ...)"
    Write-Host "  outbound_device_id       - e.g. V8-T501-01 (auto from site code)"
    Write-Host "  machine_sync_ip          - this site's biometric device IP"
    Write-Host "  machine_sync_machine_number - device STN on that machine"
    Write-Host "  middleware_api_key       - ERP -> this PC (unique per site)"
    Write-Host "  outbound_hmac_secret     - this PC -> ERP punches (unique per site)"
    Write-Host "  cloudflare_public_hostname - e.g. v8-mw.k95foods.com (unique per site)"
    Write-Host "  pc_lan_ip                  - optional; auto-set by 3-CONFIGURE_DEVICE.cmd"
    Write-Host ""
    Write-Host "Run 1-CONFIGURE_SITE.cmd to generate keys + configs/k95-vps-snippet.env"
    Write-Host ""
}
