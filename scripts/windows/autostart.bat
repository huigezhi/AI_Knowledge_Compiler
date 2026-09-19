@echo off
echo Removes with: powershell -File "%~dp0akc.ps1" autostart -Off

echo === AKC autostart ===
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0akc.ps1" autostart
echo.
pause
