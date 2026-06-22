@echo off
title Start Cloudflare tunnel now
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_cloudflared_now.ps1"
pause
