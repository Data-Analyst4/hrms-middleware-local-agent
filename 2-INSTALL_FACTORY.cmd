@echo off
title 2 - Install Factory Middleware
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator permission...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL_ONE_CLICK.ps1" -Config configs/factory.yaml -SkipSiteInit
pause
