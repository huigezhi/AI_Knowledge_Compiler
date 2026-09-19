@echo off
echo Data and .env are kept. Full removal: powershell -File "%~dp0akc.ps1" uninstall -Purge

echo === AKC uninstall ===
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0akc.ps1" uninstall
echo.
pause
