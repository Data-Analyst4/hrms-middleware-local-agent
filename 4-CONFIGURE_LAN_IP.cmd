@echo off
title 4 - Lock PC LAN IP (static)
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator permission...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\configure_lan_static_ip.ps1" %*
pause
