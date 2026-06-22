@echo off
title Deploy New Site PC (full install)
cd /d "%~dp0"
echo.
echo ============================================================
echo   HRMS Middleware - DEPLOY NEW SITE PC
echo   Windows 10 / 11 - copy this folder anywhere, then run this
echo ============================================================
echo.
echo This will:
echo   - Stop any old middleware from a previous folder/path
echo   - Generate site keys + site.local.yaml
echo   - Install Python, venv, dependencies
echo   - Register boot autostart + Cloudflare tunnel + auto-restart
echo.
echo You will be asked: site code (V8/V9...), machine IP, STN number
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\deploy_new_site.ps1" %*
pause
