@echo off
title Recover after router / ISP / LAN IP change
setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo  HR Middleware - recover app connection to attendance machine
echo  See docs\ROUTER_AND_LAN_IP_RECOVERY.md for full steps
echo ============================================================
echo.

if /I "%~1"=="-FixLivePush" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\recover_after_network_change.ps1" -FixLivePush
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\recover_after_network_change.ps1"
)

echo.
echo If checks failed, run as Administrator:
echo   4-CONFIGURE_LAN_IP.cmd
echo   3-CONFIGURE_DEVICE.cmd
echo Then: RESTART_STACK.cmd
echo.
echo To heal device live-push: RECOVER_AFTER_NETWORK_CHANGE.cmd -FixLivePush
echo.
pause
endlocal
