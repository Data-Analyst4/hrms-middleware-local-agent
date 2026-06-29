@echo off
title Repair Cloudflare registry + autostart
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
echo Removing orphan Cloudflared registry keys...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\repair_cloudflare_registry.ps1"
if %errorlevel% neq 0 (
    echo Registry repair script failed. See errors above.
    pause
    exit /b 1
)
echo.
echo Re-applying tunnel autostart (reads configs\site.local.yaml for 1299 / site URL)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\repair_cloudflare_autostart.ps1" -StartNow
if %errorlevel% neq 0 (
    echo Tunnel autostart setup failed. See errors above.
    pause
    exit /b 1
)
echo.
echo Repair finished. Check var\logs\cloudflared-mode.txt for service or runner mode.
pause
