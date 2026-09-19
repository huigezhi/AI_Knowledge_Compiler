@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: AI Knowledge Compiler (AKC) —— Windows 一键安装 (cmd 版)
:: 用法: 双击运行, 或用 README 里的 curl 一行命令下载后执行
:: 做的事: 检查环境 -> 克隆/更新代码 -> 装依赖 + 构建扩展 -> 启动 -> 健康检查

set "REPO_URL=https://github.com/huigezhi/AI_Knowledge_Compiler.git"
set "APP_DIR=%USERPROFILE%\ai-knowledge-compiler"
set "PORT=38127"

echo ==============================================================
echo   AI Knowledge Compiler 一键安装 (Windows)
echo   安装目录: %APP_DIR%
echo ==============================================================

:: ---------- 1. 检查 git ----------
where git >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 git, 请先安装: https://git-scm.com/download/win
    pause
    exit /b 1
)

:: ---------- 2. 检查 python (需要 3.12+) ----------
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 python, 请先安装 Python 3.12+: https://www.python.org/downloads/
    echo        安装时勾选 "Add python.exe to PATH"
    pause
    exit /b 1
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>nul
if errorlevel 1 (
    echo [错误] 需要 Python 3.12+, 当前:
    python --version
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do echo [OK] %%i

:: npm 不是硬性要求: 缺了只装后端, 扩展装好 Node 后重跑即可补上
where npm >nul 2>nul
if errorlevel 1 (
    echo [注意] 未检测到 npm, 将跳过 Chrome 扩展构建。装好 Node.js 后重跑本脚本即可: https://nodejs.org
)

:: ---------- 3. 获取代码 ----------
if exist "%APP_DIR%\scripts\windows\akc.ps1" (
    echo [更新] 代码已存在, 拉取最新版本...
    git -C "%APP_DIR%" pull --ff-only
) else (
    echo [克隆] %REPO_URL% ...
    git clone "%REPO_URL%" "%APP_DIR%"
    if errorlevel 1 (
        echo [错误] 克隆失败, 请检查网络或代理设置
        pause
        exit /b 1
    )
)

:: ---------- 4. 安装 (依赖 + 构建扩展 + 生成 .env) ----------
echo [安装] 后端依赖与扩展构建 (可能需要几分钟)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%\scripts\windows\akc.ps1" install
if errorlevel 1 (
    echo [错误] 安装失败, 请查看上方报错信息
    pause
    exit /b 1
)

:: ---------- 5. 启动后端 ----------
echo [启动] 后端服务 (端口 %PORT%)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%\scripts\windows\akc.ps1" start
if errorlevel 1 (
    echo [错误] 启动失败, 可稍后手动执行 akc.ps1 start
    pause
    exit /b 1
)

:: ---------- 6. 验证 ----------
powershell -NoProfile -Command "try { $h = Invoke-RestMethod -Uri 'http://127.0.0.1:%PORT%/api/v1/health' -TimeoutSec 8; if ($h.status -ne 'ok') { exit 1 } } catch { exit 1 }"
if errorlevel 1 (
    echo [错误] 健康检查未通过, 请查看后端日志: %APP_DIR%\apps\backend\data
    pause
    exit /b 1
)
echo [OK ] 后端健康检查通过: http://127.0.0.1:%PORT%

echo.
echo ==============================================================
echo   安装完成!
echo.
if exist "%APP_DIR%\apps\extension\dist\manifest.json" (
    echo   加载扩展:  chrome://extensions -^> 开发者模式 -^> 加载已解压的扩展程序
    echo             选择: %APP_DIR%\apps\extension\dist
) else (
    echo   扩展未构建 (缺 npm): 安装 Node.js 后重跑本脚本
)
echo.
echo   连接 Obsidian 库:  双击 %APP_DIR%\scripts\windows\set-vault.bat
echo   配置 AI 编译模型:  双击 %APP_DIR%\scripts\windows\set-llm.bat  (DeepSeek / Claude / 自建)
echo   开机自启:          %APP_DIR%\scripts\windows\autostart.bat
echo.
echo   扩展设置页需要的本地令牌: %APP_DIR%\apps\backend\data\auth_token
echo ==============================================================
echo.
pause
