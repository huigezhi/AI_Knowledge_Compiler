@echo off

echo === AKC install ===
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0akc.ps1" install
echo.
pause
