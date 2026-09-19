@echo off

echo === AKC restart ===
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0akc.ps1" restart
echo.
pause
