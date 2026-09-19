@echo off
chcp 65001 >nul
rem Run the AKC backend in the FOREGROUND so you can see the logs live.
rem Close this window (or press Ctrl+C) to stop the backend.
set "BACKEND=%~dp0..\..\apps\backend"
cd /d "%BACKEND%"
if not exist ".venv\Scripts\python.exe" (
  echo [!!] Backend not installed yet. Run install.bat first.
  pause
  exit /b 1
)
echo ================================================================
echo  AKC backend (foreground)
echo  - Logs are printed below, live.
echo  - Keep this window OPEN while using the extension.
echo  - Close this window or press Ctrl+C to stop.
echo ================================================================
echo.
".venv\Scripts\python.exe" -m akc
echo.
echo [backend exited]
pause
