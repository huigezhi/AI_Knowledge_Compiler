#Requires -Version 5.1
<#
.SYNOPSIS
    AKC 一键管理脚本（安装 / 启动 / 停止 / 状态 / 卸载 / 开机自启）。

.DESCRIPTION
    所有操作都围绕同一个入口，幂等可重复执行：
      install    创建虚拟环境、装依赖、构建扩展、生成 .env
      set-vault  连接你的 Obsidian 库（自动识别已安装的库，写入 .env 并重启）
      start      后台启动后端（已运行则跳过）
      stop       停止后端
      restart    重启
      status     查看运行状态与端点健康
      autostart  注册「登录时自动启动」的计划任务（可选 -Off 取消）
      uninstall  卸载（默认保留 data/ 数据库与 .env，加 -Purge 全删）

.EXAMPLE
    .\akc.ps1 install
    .\akc.ps1 start
    .\akc.ps1 autostart     # 开机/登录后自动拉起，一次配置永久服务
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("install", "start", "stop", "restart", "status", "autostart", "set-vault", "uninstall", "open")]
    [string]$Command = "status",

    [switch]$Off,      # autostart -Off 取消自启；install 时跳过构建扩展用 -SkipExtension
    [switch]$Purge,    # uninstall -Purge 连同数据与配置一起删除
    [switch]$SkipExtension,
    [switch]$AsTask,   # autostart -AsTask 额外注册计划任务（需要管理员权限）
    [string]$VaultPath, # set-vault -VaultPath "D:\MyVault" 直接指定库路径（不给则交互选择）
    [switch]$Clear      # set-vault -Clear 清除库路径配置
)

$ErrorActionPreference = "Stop"
$Root      = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Backend   = Join-Path $Root "apps\backend"
$Extension = Join-Path $Root "apps\extension"
$Venv      = Join-Path $Backend ".venv"
$PyExe     = Join-Path $Venv "Scripts\python.exe"
$Port      = 38127
$TaskName  = "AKC Backend"

function Write-Step { param($Message) Write-Host "[AKC] $Message" -ForegroundColor Cyan }
function Write-Ok   { param($Message) Write-Host "[OK ] $Message" -ForegroundColor Green }
function Write-Warn { param($Message) Write-Host "[!! ] $Message" -ForegroundColor Yellow }

function Get-BackendPid {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($conn) { return ($conn | Select-Object -First 1).OwningProcess }
    return $null
}

function Test-Healthy {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/health" -TimeoutSec 3
        return $r.status -eq "ok"
    } catch { return $false }
}

function Invoke-Install {
    Write-Step "安装后端依赖"
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "未找到 python，请先安装 Python 3.12+ 并加入 PATH。"
    }
    if (-not (Test-Path $PyExe)) {
        & python -m venv $Venv
        if ($LASTEXITCODE -ne 0) { throw "创建虚拟环境失败" }
        Write-Ok "已创建虚拟环境"
    } else {
        Write-Ok "虚拟环境已存在，跳过"
    }

    # pip 自检：极少数情况下 venv 里 pip 包缺失（Scripts 有入口但 site-packages 没有），先自愈
    & $PyExe -m pip --version 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "pip 不可用，尝试修复（ensurepip）"
        & $PyExe -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) { & $PyExe -m ensurepip }
    }

    # 必须在包目录内用相对路径 "." —— 绝对路径 + [extras] 在 Windows 上会被 pip 当路径解析而报 WinError 3
    Push-Location $Backend
    try {
        & $PyExe -m pip install --disable-pip-version-check -q -i https://pypi.org/simple -e ".[dev]"
        $code = $LASTEXITCODE
    } finally { Pop-Location }
    if ($code -ne 0) { throw "安装 Python 依赖失败（可检查网络或改用国内镜像）" }
    Write-Ok "Python 依赖就绪"

    # 生成 .env（绝不覆盖已有配置）
    $envFile = Join-Path $Backend ".env"
    if (-not (Test-Path $envFile)) {
        Copy-Item (Join-Path $Root ".env.example") $envFile
        Write-Warn "已生成 apps\backend\.env（占位值），请按需填写 AKC_VAULT_PATH / AKC_CLAUDE_*"
    } else {
        Write-Ok ".env 已存在，保留原配置"
    }

    if (-not $SkipExtension) {
        Write-Step "构建 Chrome 扩展"
        if (Get-Command npm -ErrorAction SilentlyContinue) {
            Push-Location $Extension
            try {
                # 原生命令的 stderr（npm notice 之类）在 $ErrorActionPreference='Stop' 下
                # 会被 PowerShell 当成终止错误，这里临时降级后再看退出码。
                $eap = $ErrorActionPreference
                $ErrorActionPreference = 'Continue'
                $npmCode = 0
                $buildCode = 0
                if (-not (Test-Path (Join-Path $Extension "node_modules"))) {
                    & npm install --no-fund --no-audit
                    $npmCode = $LASTEXITCODE
                }
                if ($npmCode -eq 0) {
                    & npm run build
                    $buildCode = $LASTEXITCODE
                }
                $ErrorActionPreference = $eap
                if ($npmCode -ne 0)  { throw "npm install 失败（exit $npmCode）" }
                if ($buildCode -ne 0) { throw "扩展构建失败（exit $buildCode）" }
                Write-Ok "扩展已构建到 apps\extension\dist"
            } finally { Pop-Location }
        } else {
            Write-Warn "未找到 npm，跳过扩展构建（仅后端可用）"
        }
    }

    Write-Host ""
    Write-Ok "安装完成。下一步："
    Write-Host "     .\akc.ps1 start          # 启动服务"
    Write-Host "     .\akc.ps1 autostart      # 登录即自动启动（一次性配置）"
    $tokenFile = Join-Path $Backend "data\auth_token"
    if (Test-Path $tokenFile) {
        Write-Host "     本地令牌：$tokenFile"
    }
}

function Invoke-Start {
    if (Test-Healthy) { Write-Ok "服务已在运行（端口 $Port）"; return }
    if (-not (Test-Path $PyExe)) { throw "尚未安装，请先执行 .\akc.ps1 install" }

    $logDir = Join-Path $Backend "data"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $outLog = Join-Path $logDir "akc.out.log"
    $errLog = Join-Path $logDir "akc.err.log"

    Write-Step "启动后端（端口 $Port）"
    # 启动方式三级回退（都是标准做法，只是适配不同环境）：
    #   1) 常规 Start-Process
    #   2) -UseNewEnvironment：某些 shell 派生的会话里进程环境块存在大小写重复键
    #      （Path 与 PATH），Start-Process 会抛"已添加了具有相同键的项"；
    #      用全新环境块可绕开，且保留日志重定向
    #   3) CIM Win32_Process.Create：最底层，由 cmd 负责重定向
    $launched = $false
    $startArgs = @{
        FilePath = $PyExe
        ArgumentList = @("-m", "akc")
        WorkingDirectory = $Backend
        WindowStyle = "Hidden"
        RedirectStandardOutput = $outLog
        RedirectStandardError = $errLog
    }
    try {
        Start-Process @startArgs | Out-Null
        $launched = $true
    } catch {
        Write-Warn "常规启动失败：$($_.Exception.Message.Trim())"
    }
    if (-not $launched) {
        try {
            Start-Process @startArgs -UseNewEnvironment | Out-Null
            $launched = $true
            Write-Ok "已用干净环境块启动"
        } catch {
            Write-Warn "干净环境块启动失败：$($_.Exception.Message.Trim())"
        }
    }
    if (-not $launched) {
        # 最后兜底：CIM 创建进程（环境块取自系统，不受当前会话的重复键影响）
        Write-Warn "改用 CIM 启动"
        $cmdLine = 'cmd.exe /c "' + $PyExe + '" -m akc > "' + $outLog + '" 2> "' + $errLog + '"'
        $result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create `
            -Arguments @{ CommandLine = $cmdLine; CurrentDirectory = $Backend }
        if ($result.ReturnValue -ne 0) {
            throw "启动失败（CIM ReturnValue=$($result.ReturnValue)），请查看 $errLog"
        }
    }

    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-Healthy) {
            Write-Ok "服务已就绪：http://127.0.0.1:$Port/api/v1/health"
            $tokenFile = Join-Path $Backend "data\auth_token"
            if (Test-Path $tokenFile) { Write-Host "     本地令牌文件：$tokenFile" }
            return
        }
    }
    throw "启动超时，请查看 $errLog`n可手动启动：$PyExe -m akc（工作目录 $Backend）"
}

function Invoke-Stop {
    # 注意：$pid 是 PowerShell 只读自动变量，不能用它接收进程号
    $procId = Get-BackendPid
    if (-not $procId) { Write-Warn "服务未在运行"; return }
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800
    if (Get-BackendPid) { throw "停止失败" }
    Write-Ok "服务已停止"
}

function Invoke-Status {
    $procId = Get-BackendPid
    if (-not $procId) { Write-Warn "后端未运行"; }
    else {
        Write-Ok "后端运行中（PID $procId，端口 $Port）"
        try {
            $h = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/health" -TimeoutSec 3
            Write-Host "     version=$($h.version) schema=$($h.schema_version) env=$($h.env)"
        } catch { Write-Warn "健康检查未通过" }
        try {
            $v = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/obsidian/status" -TimeoutSec 3
            $vp = if ($v.configured) { $v.vault_path } else { "未配置" }
            Write-Host "     vault=$vp"
        } catch { }
    }
    $hasStartup = (Test-Path (Get-StartupLink)) -or (Test-Path (Get-StartupCmd))
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $auto = if ($hasStartup) { "已开启（启动文件夹）" } elseif ($task) { "已开启（计划任务）" } else { "未开启（.\akc.ps1 autostart）" }
    Write-Host "     开机自启：$auto"
}

function Get-StartupLink {
    return Join-Path ([Environment]::GetFolderPath("Startup")) "AKC Backend.lnk"
}

<# 读取 Obsidian 自己记录的库列表（%APPDATA%\obsidian\obsidian.json）。 #>
function Get-ObsidianVaults {
    $cfg = Join-Path $env:APPDATA "obsidian\obsidian.json"
    if (-not (Test-Path $cfg)) { return @() }
    try {
        $json = Get-Content $cfg -Raw -Encoding UTF8 | ConvertFrom-Json
        $list = @()
        foreach ($prop in $json.vaults.PSObject.Properties) {
            $list += [pscustomobject]@{ Path = [string]$prop.Value.path; Open = [bool]$prop.Value.open }
        }
        return $list
    } catch {
        return @()
    }
}

<# 写入/更新 .env 中的某个键（保持其余内容不变，UTF-8 无 BOM）。 #>
function Set-EnvValue([string]$key, [string]$value) {
    $envFile = Join-Path $Backend ".env"
    if (-not (Test-Path $envFile)) { Copy-Item (Join-Path $Root ".env.example") $envFile }
    $lines = @(Get-Content $envFile -Encoding UTF8)
    $replaced = $false
    $out = foreach ($line in $lines) {
        if ($line -match "^\s*$([regex]::Escape($key))\s*=") { $replaced = $true; "$key=$value" } else { $line }
    }
    if (-not $replaced) { $out += "$key=$value" }
    # 必须写 UTF-8 无 BOM：带 BOM 会让第一个键名多出 \ufeff，破坏配置解析
    [System.IO.File]::WriteAllLines($envFile, $out, (New-Object System.Text.UTF8Encoding($false)))
}

function Invoke-SetVault {
    # 清除配置
    if ($Clear) {
        Set-EnvValue "AKC_VAULT_PATH" ""
        Write-Ok "已清除 Obsidian 库路径配置"
        try {
            Invoke-Stop
            Invoke-Start
        } catch {
            Write-Warn "后端重启未成功：$($_.Exception.Message.Trim())；稍后双击 start.bat 生效"
        }
        Write-Host "     现在写入 Obsidian 会返回未配置错误"
        return
    }

    $vault = $VaultPath

    if (-not $vault) {
        $detected = @(Get-ObsidianVaults)
        if ($detected.Count -gt 0) {
            Write-Step "检测到以下 Obsidian 库"
            for ($i = 0; $i -lt $detected.Count; $i++) {
                $suffix = if ($detected[$i].Open) { "   （Obsidian 当前打开）" } else { "" }
                Write-Host ("     {0}) {1}{2}" -f ($i + 1), $detected[$i].Path, $suffix)
            }
            Write-Host ""
        }
        Write-Host "     选择序号，或直接粘贴 / 把文件夹拖进本窗口，然后回车（直接回车=取消）"
        $answer = Read-Host "     你的 Obsidian 库"
        if (-not $answer) { Write-Warn "已取消"; return }
        if ($answer -match '^\d+$' -and $detected.Count -ge [int]$answer -and [int]$answer -ge 1) {
            $vault = $detected[[int]$answer - 1].Path
        } else {
            $vault = $answer
        }
    }

    $vault = $vault.Trim().Trim('"').TrimEnd('\', '/')
    if (-not (Test-Path $vault -PathType Container)) {
        throw "路径不存在或不是文件夹：$vault"
    }

    Write-Step "写入配置 apps\backend\.env"
    Set-EnvValue "AKC_VAULT_PATH" ($vault -replace '\\', '/')
    Write-Ok "AKC_VAULT_PATH = $vault"

    # 重启后端让配置生效；启动失败时不要中断，配置本身已经写好了
    try {
        Invoke-Stop
        Invoke-Start
    } catch {
        Write-Warn "后端重启未成功：$($_.Exception.Message.Trim())"
        Write-Host "     配置已写入，稍后双击 start.bat 即可生效"
    }
    Write-Host ""
    try {
        $status = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/obsidian/status" -TimeoutSec 5
        if ($status.configured) {
            Write-Ok "Obsidian 已连接：$($status.vault_path)"
            Write-Host "     AI 笔记会写到：$($status.vault_path)\$($status.raw_folder)（原始对话）"
            Write-Host "                    $($status.vault_path)\$($status.knowledge_folder)（提炼的知识）"
            Write-Host "     回到扩展侧边栏点「写入 Obsidian」即可。（首次写入时自动创建这些子目录）"
        } else {
            Write-Warn "配置已写入，但后端仍报告未配置：$($status | ConvertTo-Json -Compress)"
        }
    } catch {
        Write-Warn "无法确认状态（$($_.Exception.Message.Trim())），请手动访问 http://127.0.0.1:$Port/api/v1/obsidian/status"
    }
}

function Get-StartupCmd {
    return Join-Path ([Environment]::GetFolderPath("Startup")) "AKC Backend.cmd"
}

function Remove-StartupEntries {
    $removed = @()
    foreach ($p in @((Get-StartupLink), (Get-StartupCmd))) {
        if (Test-Path $p) {
            Remove-Item $p -Force -ErrorAction SilentlyContinue
            $removed += $p
        }
    }
    return $removed
}

function Invoke-Autostart {
    if ($Off) {
        $removed = Remove-StartupEntries
        $removed | ForEach-Object { Write-Ok "已移除启动项：$_" }
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Ok "已取消开机自启"
        return
    }

    # 用「启动文件夹」实现登录自启：不需要管理员权限，也不需要 NSSM 之类的服务包装器。
    # 注：Register-ScheduledTask 在根目录注册任务会要求管理员权限（实测报"拒绝访问"），
    #     因此默认不采用计划任务（需要时可加 -AsTask，并自行以管理员身份运行）。
    $ps = (Get-Command powershell.exe).Source
    $script = Join-Path $PSScriptRoot "akc.ps1"
    $args = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`" start"

    $created = $null
    # 首选 .lnk（可设置为最小化，登录时不弹窗）；COM 不可用时退回 .cmd
    try {
        $link = Get-StartupLink
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($link)
        $shortcut.TargetPath = $ps
        $shortcut.Arguments = $args
        $shortcut.WorkingDirectory = $PSScriptRoot
        $shortcut.WindowStyle = 7
        $shortcut.Description = "AI Knowledge Compiler backend"
        $shortcut.Save()
        if (Test-Path $link) { $created = $link }
    } catch {
        Write-Warn "创建快捷方式失败（$($_.Exception.Message.Trim())），改用 .cmd 启动项"
    }

    if (-not $created) {
        $cmdPath = Get-StartupCmd
        $lines = @(
            "@echo off",
            "rem AI Knowledge Compiler backend - 登录时自动启动",
            "`"$ps`" $args"
        )
        Set-Content -Path $cmdPath -Value $lines -Encoding Default
        if (Test-Path $cmdPath) { $created = $cmdPath }
    }

    if (-not $created) { throw "创建启动项失败，请检查启动文件夹是否可写" }
    Write-Ok "已开启登录自启（启动文件夹，无需管理员权限）"
    Write-Host "     启动项：$created"
    Write-Host "     取消：.\akc.ps1 autostart -Off"

    if ($AsTask) {
        Write-Step "另外注册计划任务（需要管理员权限，失败不影响上面的启动项）"
        try {
            $action = New-ScheduledTaskAction -Execute $ps -Argument $args
            $trigger = New-ScheduledTaskTrigger -AtLogOn
            $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
            Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
                -Description "AI Knowledge Compiler 本地后端" -Force | Out-Null
            Write-Ok "已注册计划任务：$TaskName"
        } catch {
            Write-Warn "计划任务注册失败（$($_.Exception.Message.Trim())）——启动文件夹方式已生效，可忽略"
        }
    }
}

function Invoke-Uninstall {
    Write-Step "停止服务"
    Invoke-Stop
    Write-Step "取消开机自启"
    Remove-StartupEntries | Out-Null
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

    if (Test-Path $Venv) { Remove-Item -Recurse -Force $Venv; Write-Ok "已删除 .venv" }
    $dist = Join-Path $Extension "dist"
    if (Test-Path $dist) { Remove-Item -Recurse -Force $dist; Write-Ok "已删除 扩展 dist" }

    if ($Purge) {
        foreach ($p in @((Join-Path $Backend "data"), (Join-Path $Backend ".env"), (Join-Path $Extension "node_modules"))) {
            if (Test-Path $p) { Remove-Item -Recurse -Force $p; Write-Ok "已删除 $p" }
        }
        Write-Warn "数据库与配置已一并删除（不可恢复）"
    } else {
        Write-Host "     已保留 data\（数据库与令牌）与 .env；如需彻底清除请加 -Purge"
    }
    Write-Ok "卸载完成"
}

switch ($Command) {
    "install"    { Invoke-Install }
    "start"      { Invoke-Start }
    "stop"       { Invoke-Stop }
    "restart"    { Invoke-Stop; Invoke-Start }
    "status"     { Invoke-Status }
    "autostart"  { Invoke-Autostart }
    "set-vault"  { Invoke-SetVault }
    "uninstall"  { Invoke-Uninstall }
    "open"       { Start-Process "http://127.0.0.1:$Port/api/v1/health" }
}
