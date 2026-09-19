@echo off

echo === AKC status ===
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0akc.ps1" status
echo.
pause
