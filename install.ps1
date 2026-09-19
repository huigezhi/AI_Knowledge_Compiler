# AI Knowledge Compiler (AKC) —— Windows 一键安装 (PowerShell)
# 一行命令运行（复制到 PowerShell / cmd / "运行"窗口）:
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/huigezhi/AI_Knowledge_Compiler/main/install.ps1 | iex"
#
# 做的事: 检查环境 -> 克隆/更新代码 -> 装后端依赖 -> 构建扩展 -> 生成 .env -> 启动 -> 健康检查

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/huigezhi/AI_Knowledge_Compiler.git"
$AppDir  = Join-Path $env:USERPROFILE "ai-knowledge-compiler"
$Port    = 38127

function Fail {
    param($Message)
    Write-Host "[错误] $Message" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

Write-Host "=============================================================="
Write-Host "  AI Knowledge Compiler 一键安装 (Windows)"
Write-Host "  安装目录: $AppDir"
Write-Host "=============================================================="

# ---------- 1. 检查 git ----------
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "未检测到 git, 请先安装: https://git-scm.com/download/win"
}

# ---------- 2. 检查 python (需要 3.12+) ----------
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Fail "未检测到 python, 请先安装 Python 3.12+: https://www.python.org/downloads/ (安装时勾选 'Add python.exe to PATH')"
}
$pyVer = & python -c "import sys; print(sys.version_info.major * 100 + sys.version_info.minor)"
if ([int]$pyVer -lt 312) {
    Fail "需要 Python 3.12+, 当前为 $(python --version 2>&1)。请升级: https://www.python.org/downloads/"
}

# npm 不是硬性要求: 缺了只装后端, 扩展稍后用 Node 装好再构建
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "[注意] 未检测到 npm, 将跳过 Chrome 扩展构建。装好 Node.js 后重跑本脚本即可补上: https://nodejs.org" -ForegroundColor Yellow
}

# ---------- 3. 获取代码 ----------
$Marker = Join-Path $AppDir "scripts\windows\akc.ps1"
if (Test-Path $Marker) {
    Write-Host "[更新] 代码已存在, 拉取最新版本..."
    git -C $AppDir pull --ff-only
    if ($LASTEXITCODE -ne 0) { Write-Host "[注意] git pull 失败, 使用现有代码继续" -ForegroundColor Yellow }
} else {
    Write-Host "[克隆] $RepoUrl ..."
    git clone $RepoUrl $AppDir
    if ($LASTEXITCODE -ne 0) { Fail "克隆失败, 请检查网络或代理设置" }
}

# ---------- 4. 安装 (依赖 + 构建扩展 + 生成 .env) ----------
$Akc = Join-Path $AppDir "scripts\windows\akc.ps1"
Write-Host "[安装] 后端依赖与扩展构建 (可能需要几分钟)..."
& powershell -NoProfile -ExecutionPolicy Bypass -File $Akc install
if ($LASTEXITCODE -ne 0) { Fail "安装失败, 请查看上方报错信息" }

# ---------- 5. 启动后端 ----------
Write-Host "[启动] 后端服务 (端口 $Port)..."
& powershell -NoProfile -ExecutionPolicy Bypass -File $Akc start
if ($LASTEXITCODE -ne 0) { Fail "启动失败, 请查看上方报错信息 (也可稍后手动执行 akc.ps1 start)" }

# ---------- 6. 验证 ----------
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/health" -TimeoutSec 8
    if ($health.status -ne "ok") { throw "status=$($health.status)" }
    Write-Host "[OK ] 后端健康检查通过: http://127.0.0.1:$Port" -ForegroundColor Green
} catch {
    Fail "健康检查未通过: $_"
}

$dist = Join-Path $AppDir "apps\extension\dist"
Write-Host ""
Write-Host "=============================================================="
Write-Host "  安装完成!"
Write-Host ""
if (Test-Path (Join-Path $dist "manifest.json")) {
    Write-Host "  加载扩展:  chrome://extensions -> 开发者模式 -> 加载已解压的扩展程序"
    Write-Host "             选择: $dist"
} else {
    Write-Host "  扩展未构建 (缺 npm): 安装 Node.js 后重跑本脚本"
}
Write-Host ""
Write-Host "  连接 Obsidian 库:  双击 $AppDir\scripts\windows\set-vault.bat"
Write-Host "  配置 AI 编译模型:  双击 $AppDir\scripts\windows\set-llm.bat  (DeepSeek / Claude / 自建)"
Write-Host "  开机自启:          $AppDir\scripts\windows\autostart.bat"
Write-Host ""
Write-Host "  扩展设置页需要的本地令牌: $AppDir\apps\backend\data\auth_token"
Write-Host "=============================================================="
Write-Host ""
Read-Host "按回车退出"
