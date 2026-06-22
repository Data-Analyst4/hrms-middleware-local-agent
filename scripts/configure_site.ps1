param(
    [switch]$OpenEditor,
    [switch]$ForceFromExample
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "lib\project_paths.ps1")

$projectRoot = Get-ProjectRoot -ScriptRoot $PSScriptRoot
Set-Location $projectRoot

Write-Host "== Configure Site PC ==" -ForegroundColor Cyan
Write-Host "Project folder: $projectRoot"
Write-Host "Windows: $([System.Environment]::OSVersion.VersionString)"

if (-not (Test-IsWindows10OrLater)) {
    Write-Warning "This stack is tested on Windows 10 and 11."
}

$created = Ensure-SiteLocalConfig -ProjectRoot $projectRoot -ForceFromExample:$ForceFromExample
$sitePath = Get-SiteLocalConfigPath -ProjectRoot $projectRoot

Show-SiteConfigChecklist -ProjectRoot $projectRoot

$dllRel = Read-SiteYamlValue -Key "machine_sdk_dll_path" -ProjectRoot $projectRoot
$dllAbs = Join-Path $projectRoot ($dllRel -replace '/', '\')
if (Test-Path $dllAbs) {
    Write-Host "SDK DLL found: $dllRel" -ForegroundColor Green
} else {
    Write-Host "SDK DLL missing: $dllAbs" -ForegroundColor Red
    Write-Host "Copy sdk_extracted into the project folder or update machine_sdk_dll_path in site.local.yaml."
}

$deviceIp = Read-SiteYamlValue -Key "machine_sync_ip" -ProjectRoot $projectRoot
if ($deviceIp -match '^192\.168\.1\.100$' -or $deviceIp -eq "") {
    Write-Host ""
    Write-Host "WARNING: machine_sync_ip still looks like the template default." -ForegroundColor Yellow
    Write-Host "Set the real biometric device IP in: $sitePath"
}

if ($OpenEditor -or $created) {
    Write-Host ""
    Write-Host "Opening site.local.yaml for editing..." -ForegroundColor Cyan
    Start-Process notepad.exe -ArgumentList $sitePath
}

Write-Host ""
Write-Host "Next: run 2-INSTALL_FACTORY.cmd or SETUP_NEW_PC.cmd as Administrator." -ForegroundColor Green
