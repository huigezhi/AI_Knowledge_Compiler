@echo off

echo === AKC start ===
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0akc.ps1" start
echo.
pause
