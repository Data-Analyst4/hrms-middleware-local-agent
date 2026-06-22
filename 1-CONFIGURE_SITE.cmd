@echo off
title 1 - Configure Site PC
cd /d "%~dp0"
echo.
echo Creates/edits configs\site.local.yaml (per-PC settings).
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\configure_site.ps1" -OpenEditor
echo.
pause
