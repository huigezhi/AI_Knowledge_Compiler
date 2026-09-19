# 一键脚本

一次配置，永久服务。分两套：**本地 Windows** 与 **远程 VPS（Linux）**。

```
scripts/
├── windows/                 # 本机一键管理（双击 .bat 即可）
│   ├── install.bat          # 安装：venv + 依赖 + 扩展构建 + 生成 .env
│   ├── start.bat            # 启动后端（后台常驻）
│   ├── start-foreground.bat # 前台启动（日志直接打在窗口里，排错用）
│   ├── stop.bat             # 停止
│   ├── restart.bat          # 重启
│   ├── status.bat           # 状态与健康检查
│   ├── set-vault.bat        # 连接 Obsidian 库（自动识别已安装的库）
│   ├── autostart.bat        # 登录即自动启动（一次性配置）
│   ├── build-extension.bat  # 改完适配器后重建扩展
│   ├── uninstall.bat        # 卸载（保留数据；-Purge 全删）
│   └── akc.ps1              # 上面所有命令的实现（也可命令行调用）
└── linux/                   # VPS 常驻服务
    ├── install.sh           # 安装为 systemd 服务（开机自启 + 崩溃自动拉起）
    ├── uninstall.sh         # 卸载服务
    ├── deploy.sh            # 从本机同步代码到 VPS 并重启
    └── akc.service          # systemd 单元模板
```

> Windows 脚本统一为 UTF-8 **带 BOM** 编码——PowerShell 5.1 读取无 BOM 的 UTF-8 会按 GBK 解码，
> 中文注释会变成乱码并破坏语法。修改 `akc.ps1` 后请保持 BOM。

---

## Windows 本机

**双击即可**（推荐）：

1. 双击 `scripts\windows\install.bat` —— 装依赖、构建扩展、生成 `.env`
2. 填 `apps\backend\.env`（`AKC_VAULT_PATH`、Claude 相关）
3. 双击 `start.bat`
4. 双击 `autostart.bat` —— **以后开机登录就自动跑起来了**，不用再管

命令行等价用法：

```powershell
cd scripts\windows
.\akc.ps1 install      # 幂等，可重复执行
.\akc.ps1 start
.\akc.ps1 status       # 看运行状态、版本、Vault 是否配置
.\akc.ps1 autostart    # 开启登录自启（写启动文件夹，无需管理员）
.\akc.ps1 autostart -Off
.\akc.ps1 uninstall            # 保留数据与 .env
.\akc.ps1 uninstall -Purge     # 连数据库和配置一起删
```

说明：

- `install` 不会覆盖已有的 `.env` 与数据库；
- `autostart` 用「**启动文件夹快捷方式**」实现登录自启：不需要管理员权限，也不需要 NSSM。
  首次优先创建 `.lnk`（最小化窗口），COM 不可用时自动退回 `.cmd`；
  `status` 会显示当前自启状态，`autostart -Off` 或 `uninstall` 会清理。
- 只有在确实需要「计划任务」时才加 `-AsTask`：**根目录注册任务要求管理员权限**，
  非管理员运行会报「拒绝访问」（HRESULT 0x80070005）——所以默认不走这条路。
- `start` 采用三级回退（常规 Start-Process → 干净环境 → CIM），兼容某些会话里
  进程环境块存在 `Path`/`PATH` 重复键的异常情况；
  若仍启动不了，用 `start-foreground.bat`（前台跑，日志直接可见）最直观。
- 首次启动会在 `apps\backend\data\auth_token` 生成本地令牌，扩展必须填它。

### 连接 Obsidian 库

Vault 路径属于**后端配置**（写在 `apps\backend\.env` 的 `AKC_VAULT_PATH`），
不在扩展的设置页里。三种指定方式，任选其一：

```powershell
# 1) 双击 set-vault.bat —— 自动列出你电脑上已安装的 Obsidian 库，输入序号即可
# 2) 把库文件夹直接拖到 set-vault.bat 上（路径作为参数传入）
# 3) 命令行指定
.\akc.ps1 set-vault -VaultPath "D:\MyVault"
.\akc.ps1 set-vault -Clear          # 取消连接
```

脚本会校验路径、按需创建/更新 `.env` 中的 `AKC_VAULT_PATH`（写 UTF-8 无 BOM，避免首键被 BOM 破坏）、
重启后端，并回读 `/api/v1/obsidian/status` 确认结果。AKC 只在库里新建
`01_Raw` / `02_Inbox` / `03_Knowledge` 三个子目录，不改动已有笔记。

---

## 远程 VPS（Linux）

在 VPS 上（Ubuntu/Debian，需 root）：

```bash
sudo ./install.sh                                  # 装到 /opt/akc，systemd 常驻
sudo ./install.sh --vault /opt/akc/vault           # 指定 Vault 目录
sudo ./install.sh --domain akc.example.com         # 额外装 Caddy 自动 HTTPS
sudo ./install.sh --dir /srv/akc --user akc        # 自定义目录与用户
```

安装完即为「一次配置、永久服务」：

- `systemctl enable --now akc` → 开机自启
- `Restart=always` → 崩溃/异常退出 5 秒后自动拉起
- `journalctl -u akc -f` → 实时日志
- 配置在 `/etc/akc/akc.env`（权限 600，含随机生成的访问令牌）

卸载：

```bash
sudo ./uninstall.sh            # 只停服务（保留数据）
sudo ./uninstall.sh --purge    # 连目录与配置一起删
```

从本机更新代码（改完代码一条命令生效）：

```bash
./deploy.sh user@1.2.3.4                 # 同步 + 重启 + 健康检查
./deploy.sh user@1.2.3.4 --dir /srv/akc
```

---

## 后端在 VPS 上时，扩展怎么连？（重要）

AKC 是 local-first 设计：扩展默认访问 `http://127.0.0.1:38127`。
后端搬到 VPS 后有两种接法，**推荐第一种**：

### 方案 1：SSH 隧道（推荐，零改动）

```bash
ssh -N -L 38127:127.0.0.1:38127 user@your-vps
```

本地 `127.0.0.1:38127` 会被转发到 VPS，扩展的 Options **完全不用改**，
流量走 SSH 加密，VPS 上的服务仍然只监听回环地址 —— 最安全、最省事。

Windows 上可以用 `autossh`，或把这条命令加进上面的 `autostart.bat` 之前。

### 方案 2：HTTPS 域名

用 `install.sh --domain akc.example.com` 装 Caddy 自动签发证书，然后：

1. 扩展 Options 里后端地址改成 `https://akc.example.com`
2. **点「保存」**：扩展会弹窗申请访问该域名的权限，选「允许」
   （MV3 的扩展 fetch 受 `host_permissions` 限制，默认只声明了本地回环地址，
   远程地址需要动态授权；拒绝授权会提示"未授权访问 …"）
3. VPS 上改 `/etc/akc/akc.env` 的 `AKC_CORS_ORIGINS=chrome-extension://<你的扩展ID>`
4. `systemctl restart akc`

> **不要**把 `AKC_HOST` 改成 `0.0.0.0`：生产模式下配置校验会直接拒绝非回环监听，
> 这是为了防止本地服务被裸奔到公网。对外一律走反向代理或 SSH 隧道。

### 采集会受影响吗？

不会。采集发生在浏览器本地（content script 读页面 DOM），与后端在哪无关；
受影响的只有"把结果送到后端"这一段。三件事要满足：

1. **网络可达**：浏览器能连到 VPS（国外 VPS 受公网质量影响，丢包会让导入变慢或失败）；
2. **主机权限**：见方案 2 第 2 步（方案 1 的 SSH 隧道不需要，仍是 127.0.0.1）；
3. **CORS**：VPS 上把扩展来源写进 `AKC_CORS_ORIGINS`。

另外注意：如果你用 Clash 等代理上网，确认代理规则**放行本地回环地址**，
否则扩展连 `127.0.0.1` 也走代理会连不上后端。

### 放国外 VPS 的真正动机：Claude API 可达

把后端放国外 VPS 最大的收益不是采集，而是**编译**——后端调用 Claude API 不再需要额外代理。
代价是：原始对话会离开本机（违背 local-first 的隐私前提），且 Vault 在 VPS 上，
本机 Obsidian 需要靠 Git / Syncthing 同步。

如果只是想要 Claude API 可达，又不想让数据出本机，更稳妥的组合是：
**后端留在本机 + 给编译请求单独配代理**（`AKC_CLAUDE_BASE_URL` 指向你的代理网关）。

### Vault 同步提醒

Vault 在 VPS 上时，本机 Obsidian 看不到文件。可选：
- 用 **Obsidian Git 插件**定时 commit/push；
- 用 **Syncthing** 双向同步；
- 或者干脆只在 VPS 上生成知识，再定期把 `03_Knowledge/` 拉回本机。

---

## 常见问题

## 附：网络受限时的推送工具

`github.com` 不通但 `api.github.com` 通时（常见于国内网络），`git push` 会超时。
可用 `tools/push_via_api.py` 走 REST API 推送，提交信息与目录结构完整保留：

```bash
BASE=$(git ls-remote https://github.com/huigezhi/AI_Knowledge_Compiler.git main | cut -f1)
python scripts/tools/push_via_api.py <your_token> "$BASE" <commit_sha1> [<commit_sha2> ...]
```

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `install.bat` 报找不到 python | 安装 Python 3.12+ 并勾选 "Add to PATH" |
| pip 安装很慢/失败 | 脚本用官方源；可改 `akc.ps1` 里的 `-i https://pypi.org/simple` 为国内镜像 |
| 双击 bat 一闪而过 | 直接命令行运行 `powershell -File akc.ps1 start` 看报错 |
| VPS 上 `systemctl status akc` 失败 | `journalctl -u akc -n 50` 看日志，多半是 `.env` 里 Claude 配置不完整 |
| 想换端口 | 改 `/etc/akc/akc.env` 的 `AKC_PORT` 后 `systemctl restart akc` |
