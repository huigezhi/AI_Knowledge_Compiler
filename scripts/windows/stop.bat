@echo off

echo === AKC stop ===
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0akc.ps1" stop
echo.
pause
