@echo off
chcp 65001 >nul
echo ================================================================
echo  Configure the AI model used to compile knowledge
echo ----------------------------------------------------------------
echo  Pick a provider, paste your API key, and this script will
echo    1. send a tiny test request to verify the key really works
echo    2. write apps\backend\.env
echo    3. restart the backend
echo.
echo  Supported:
echo    1) DeepSeek          (direct in China, cheap)
echo    2) Claude/Anthropic
echo    3) custom endpoint   (you supply base_url)
echo.
echo  Your key is stored locally in apps\backend\.env only.
echo  Your existing notes are never touched.
echo ================================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0akc.ps1" set-llm %*

echo.
pause
