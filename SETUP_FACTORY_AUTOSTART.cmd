@echo off
title V8 Factory Autostart Setup
cd /d "%~dp0"
echo Registering middleware + Cloudflare tunnel autostart (factory config)...
echo.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator permission...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_factory_autostart.ps1" -Config configs/factory.yaml -StartNow
pause
