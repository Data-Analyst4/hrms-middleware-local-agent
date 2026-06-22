@echo off
title Setup New PC (configure + install)
cd /d "%~dp0"
echo.
echo ============================================================
echo   HRMS Middleware - New PC Setup (Windows 10 / 11)
echo ============================================================
echo.
echo This folder can be copied anywhere (USB, D:\Apps, etc.).
echo.
echo Step 1: Create/edit per-PC settings (site.local.yaml)
echo Step 2: Install Python, middleware, tunnel autostart
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\configure_site.ps1"
echo.
echo Edit configs\site.local.yaml if needed, then press a key to install...
pause
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator permission for install...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL_ONE_CLICK.ps1" -Config configs/factory.yaml -SkipSiteInit
pause
