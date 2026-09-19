@echo off
chcp 65001 >nul
echo ================================================================
echo  Connect your Obsidian vault to AKC
echo ----------------------------------------------------------------
echo  Three ways to specify the vault:
echo    1. drag a vault folder onto this .bat file, or
echo    2. run this .bat and type/paste the folder path, or
echo    3. run this .bat and pick a number from the detected list
echo.
echo  It writes AKC_VAULT_PATH into apps\backend\.env and restarts
echo  the backend. No admin rights needed. Your existing notes are
echo  not touched - AKC only creates 01_Raw / 02_Inbox / 03_Knowledge.
echo ================================================================
echo.

if "%~1"=="" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0akc.ps1" set-vault
) else (
  echo Using vault path passed in: %~1
  echo.
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0akc.ps1" set-vault -VaultPath "%~1"
)
echo.
pause
