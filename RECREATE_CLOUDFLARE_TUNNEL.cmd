@echo off
title Recreate Cloudflare tunnel credentials (V8 / site from yaml)
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
echo.
echo This fixes: Missing credentials file ...\.cloudflared\*.json
echo.
echo It will DELETE the remote Cloudflare tunnel named in site.local.yaml
echo and create a NEW tunnel + credentials on THIS PC.
echo.
echo If the OLD V8 PC still has the .json file, copying it is safer — see docs.
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\repair_cloudflare_credentials.ps1" -Force
pause
