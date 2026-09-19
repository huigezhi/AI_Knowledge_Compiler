@echo off
setlocal
set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" (
  echo [!!] chrome.exe not found. Please check your Chrome install path.
  pause
  exit /b 1
)

set "PROFILE=%LOCALAPPDATA%\AKC-DebugProfile"

echo ================================================================
echo  Start Chrome with remote debugging port 9222
echo.
echo  NOTE: this uses a SEPARATE browser profile
echo  (%PROFILE%).
echo  - Chrome 136+ blocks the debug port on your DEFAULT profile,
echo    so a dedicated profile is required.
echo  - It runs side-by-side with your normal Chrome. No need to
echo    close your current browser.
echo  - First run: log in to your AI platforms (doubao / deepseek /
echo    chatglm) once in the window that opens. Logins are kept in
echo    this profile, so future runs need no login again.
echo  - No data is copied or uploaded from your normal profile.
echo ================================================================
echo.

start "" "%CHROME%" --remote-debugging-port=9222 --no-first-run --no-default-browser-check --user-data-dir="%PROFILE%" https://www.doubao.com/chat/

echo [OK] Chrome started with debugging port 9222 and profile AKC-DebugProfile.
echo.
echo Next steps:
echo   1. In the new Chrome window, log in to doubao
echo      (and deepseek / chatglm if you also want them fixed)
echo   2. Go back to the chat and tell the assistant: logged in
echo   3. The assistant will read the page structure automatically
echo      and calibrate the adapters
echo.
echo When finished, just close this Chrome window.
echo ================================================================
pause
