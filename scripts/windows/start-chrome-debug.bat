@echo off
chcp 65001 >nul
setlocal
set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" (
  echo [!!] 找不到 chrome.exe，请手动确认安装路径
  pause
  exit /b 1
)

echo ================================================================
echo  启动带调试端口的 Chrome（用于读取 AI 平台真实页面结构）
echo ----------------------------------------------------------------
echo  用途：让 AI 助手能直接读你已登录的对话页面，从而修好适配器。
echo  窗口会正常显示，你全程能看到它打开了什么页面。
echo  不复制、不上传任何登录数据。
echo ================================================================
echo.

tasklist /FI "IMAGENAME eq chrome.exe" | find /I "chrome.exe" >nul
if not errorlevel 1 (
  echo [!!] Chrome 正在运行，必须先完全退出才能开启调试端口。
  echo.
  echo      请这样做：
  echo        1. 关闭所有 Chrome 窗口
  echo        2. 按 Ctrl+Shift+Esc 打开任务管理器，
  echo           找到所有 "Google Chrome" 进程并结束任务
  echo        3. 重新双击本脚本
  echo.
  pause
  exit /b 1
)

start "" "%CHROME%" --remote-debugging-port=9222 --no-first-run --no-default-browser-check

echo [OK] Chrome 已带调试端口 9222 启动。
echo.
echo 接下来：
echo   1. 保持这个 Chrome 窗口开着
echo   2. 回到对话里，告诉 AI「已启动」
echo   3. AI 会自动打开豆包/DeepSeek 读取结构并修好适配器
echo.
echo 用完请关闭这个 Chrome 窗口（调试端口随窗口关闭）。
echo ================================================================
pause
