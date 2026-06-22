@echo off
REM Temporary public URL for ERP -> middleware (changes each run until permanent DNS is set).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_cloudflare_quick_tunnel.ps1"
pause
