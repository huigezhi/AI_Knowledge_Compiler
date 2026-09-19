@echo off
chcp 65001 >nul
echo === AKC rebuild Chrome extension ===
echo.
set "EXT=%~dp0..\..\apps\extension"
pushd "%EXT%"
call npm run build
set "CODE=%ERRORLEVEL%"
popd
echo.
if "%CODE%"=="0" (
  echo Build OK. Output: apps\extension\dist
  echo Next: open chrome://extensions and click the reload icon on the AKC card.
) else (
  echo Build FAILED with exit code %CODE%
)
echo.
pause
