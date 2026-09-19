# AI Knowledge Compiler (AKC)

**多平台 AI 对话采集 → Claude 知识编译 → Obsidian 知识库**

AKC 不是一个“AI 聊天导出器”，而是一个 **AI 对话知识编译器**：把你在 ChatGPT、Claude、DeepSeek、豆包、智谱清言网页端产生的对话当作原始知识流，统一采集、存档、去重、关联、提炼，再把**稳定知识**写入 Obsidian。

> 核心理念：**Raw 与 Knowledge 分离；AI 编译知识，人类审核知识。**

---

## 1. 它解决什么问题

| 痛点 | AKC 的做法 |
| --- | --- |
| 对话散落在 5+ 个平台 | 统一收敛到 **Universal Conversation Schema**，一套数据模型 |
| 导出即丢失上下文 | 原始消息永久留存，**编译过程永不覆盖 Raw** |
| 导出只是摘要，不可复用 | 输出可复用的 `fact / concept / method / heuristic / decision / question / hypothesis / opinion` |
| 同一知识点反复出现 | Candidate Retrieval + Duplicate Detector + Merge Planner，跨对话合并 |
| AI 说得不一定对 | Candidate / Verified 分离，**Verified 不会被低置信度 Candidate 静默覆盖** |
| 数据在本地还是云端 | Local-first：SQLite + Vault 全在本地，只有点“编译”时才把上下文发给 Claude |

---

## 2. 架构

```
┌───────────────────────────────────────────────┐
│              Chrome Extension (MV3)           │
│  Side Panel / Options / Content Script        │
│  Provider Adapters: ChatGPT Claude DeepSeek   │
│                     豆包 智谱清言              │
└────────────────────┬──────────────────────────┘
                     │ http://127.0.0.1:38127  (+ X-AKC-Token)
                     ▼
┌───────────────────────────────────────────────┐
│                Local Backend (FastAPI)        │
│  routers → services → repositories            │
│  ├ Conversation Normalizer / Hasher           │
│  ├ Claude Knowledge Compiler (pipeline)       │
│  ├ Search (FTS5) / Dedup / Merge Planner      │
│  ├ Job Queue (SQLite, retry + backoff)        │
│  └ Obsidian Writer (atomic, conflict-safe)    │
└───────────────┬───────────────┬───────────────┘
                ▼               ▼
        ┌──────────────┐  ┌──────────────────┐
        │ SQLite (+FTS5)│  │ Obsidian Vault   │
        │ Raw / Meta    │  │ Markdown + YAML  │
        └──────────────┘  └──────────────────┘
                │
                ▼
        ┌──────────────┐
        │  Claude API  │  ← 仅在用户触发编译时调用
        └──────────────┘
```

分层原则：**控制器不写业务逻辑，服务层不依赖 HTTP 类型，仓储层只做数据访问。**

---

## 3. 仓库结构

```
AI_Knowledge_Compiler/
├── apps/
│   ├── backend/                 # Python 3.12 + FastAPI 本地服务
│   │   ├── akc/
│   │   │   ├── config.py        # 集中配置 + 启动校验（fail fast）
│   │   │   ├── errors.py        # 类型化错误体系 + 错误码
│   │   │   ├── logging_setup.py # 结构化 JSON 日志 + request_id
│   │   │   ├── db/              # SQLAlchemy 模型 / 会话 / SQL 迁移
│   │   │   ├── repositories/    # 数据访问层
│   │   │   ├── services/        # 业务逻辑层
│   │   │   ├── compiler/        # Claude 客户端 / Prompt / 输出校验
│   │   │   └── routers/         # HTTP 控制器层
│   │   └── tests/               # pytest
│   └── extension/               # Chrome MV3 + TypeScript
│       ├── src/adapters/        # 5 个平台适配器 + selector 常量
│       ├── src/sidepanel/       # Side Panel UI
│       ├── src/options/         # Settings UI
│       ├── src/background/      # Service Worker
│       ├── src/shared/          # Schema / API client / settings
│       └── tests/fixtures/      # 每平台 6 类回归 fixture
├── packages/schema/             # Universal Conversation Schema（TS + JSON Schema）
├── docs/                        # 架构 / API / 数据模型 / 适配器 / 编译 / 测试
└── docs/requirements/           # 需求设计原文（可追溯）
```

---

## 4. 快速开始

> 完整的首次上手流程（含令牌配置、采集、编译、写入、审核与排查）见
> [docs/usage.md](docs/usage.md)。以下是最小命令集。

### 4.1 一键安装

复制对应系统的一行命令到终端运行，从克隆代码到验证完成全自动，无需手动 clone：

**Windows（PowerShell，推荐）**

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/huigezhi/AI_Knowledge_Compiler/main/install.ps1 | iex"
```

命令直接从网络执行，不在本地留下安装脚本。也可以[下载 install.ps1](https://raw.githubusercontent.com/huigezhi/AI_Knowledge_Compiler/main/install.ps1) 后执行，或使用 [install.bat](https://raw.githubusercontent.com/huigezhi/AI_Knowledge_Compiler/main/install.bat)（双击运行）。

**Windows（cmd）**

```bat
curl -fsSL -o %TEMP%\install.bat https://raw.githubusercontent.com/huigezhi/AI_Knowledge_Compiler/main/install.bat && %TEMP%\install.bat
```

**Ubuntu / Debian**

```bash
curl -fsSL https://raw.githubusercontent.com/huigezhi/AI_Knowledge_Compiler/main/install.sh -o /tmp/akc-install.sh && bash /tmp/akc-install.sh
```

> 不要用 `bash <(curl ...)`：不少 VPS 没有 `/dev/fd`，进程替换会报
> `bash: /dev/fd/63: No such file or directory`。上面的写法先落盘再执行，任何环境都能跑。
> 国内 VPS 访问 GitHub / PyPI 慢时，可在命令前加镜像，例如：
> `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple bash /tmp/akc-install.sh`。

脚本做的事：检查环境 → 克隆/更新代码到 `~/ai-knowledge-compiler`（Linux 装到 `/opt/akc`）→
装依赖 → 构建 Chrome 扩展 → 生成 `.env` → 启动后端 → 健康检查。

### 4.1.1 前置要求

- **Windows**：[git](https://git-scm.com/download/win) + [Python 3.12+](https://www.python.org/downloads/)（安装时勾选 *Add python.exe to PATH*）。
  [Node.js](https://nodejs.org) 可选 —— 没有它只装后端，装好后重跑脚本即可补建扩展。
- **Ubuntu / Debian**：无（脚本会用 apt 自动安装缺失的 git / curl / python3；
  系统自带 Python 低于 3.12 时，Ubuntu 会自动走 deadsnakes 装 3.12）。
  Linux 版安装为 systemd 服务，一般装在 VPS 上，本地 Chrome 扩展走 SSH 隧道连接。

### 4.2 本地后端

```bash
cd apps/backend
python -m venv .venv
./.venv/Scripts/python -m pip install -e ".[dev]"   # Windows
# source .venv/bin/activate && pip install -e ".[dev]"  # macOS / Linux
python -m akc                                       # http://127.0.0.1:38127
```

健康检查：

```bash
curl http://127.0.0.1:38127/api/v1/health
```

启动时会在 `AKC_DATA_DIR` 生成/读取本地 token（`auth_token` 文件），扩展的每次写请求都必须带 `X-AKC-Token`。

### 4.3 Chrome 扩展

```bash
cd apps/extension
npm install
npm run build         # 产物在 apps/extension/dist
```

1. 打开 `chrome://extensions`，开启「开发者模式」
2. 「加载已解压的扩展程序」→ 选择 `apps/extension/dist`
3. 在扩展 Options 页填写后端地址与本地 token（点击「测试连接」验证）
4. Vault 路径 / 模型 API Key / 模型 ID 属于**后端配置**，双击脚本即可填：
   `scripts/windows/set-vault.bat` 选 Obsidian 库，`scripts/windows/set-llm.bat` 配模型服务
   （支持 DeepSeek / Claude / 自建端点，会实测 Key 可用性）。
   手写则是复制 `.env.example` 为 `apps/backend/.env` 后填写
   （`AKC_VAULT_PATH`、`AKC_LLM_API_KEY`、`AKC_LLM_MODEL`、`AKC_LLM_PROVIDER`），重启后端生效
5. 打开任意受支持平台 → 打开 Side Panel → 「保存当前对话」

### 4.4 一键脚本（推荐：一次配置，永久服务）

不想每次手敲命令，就用 `scripts/` 下的一键脚本 —— 双击即可：

| 平台 | 位置 | 说明 |
| --- | --- | --- |
| Windows | `scripts\windows\install.bat` | 装依赖 + 构建扩展 + 生成 `.env` |
| Windows | `scripts\windows\start.bat` / `stop.bat` / `status.bat` | 启停与状态 |
| Windows | `scripts\windows\autostart.bat` | **登录即自动启动**，配置一次即可 |
| Linux / VPS | `scripts/linux/install.sh` | 安装为 systemd 服务（开机自启 + 崩溃自动拉起） |
| Linux / VPS | `scripts/linux/deploy.sh user@host` | 改完代码一条命令同步并重启 |

详见 [scripts/README.md](scripts/README.md)。
后端放到 VPS 后，扩展推荐用 **SSH 隧道** 连接（扩展配置零改动、流量加密）：
`ssh -N -L 38127:127.0.0.1:38127 user@your-vps`

### 4.5 常用命令

```bash
make bootstrap   # 装齐依赖
make test        # 后端 pytest + 前端 vitest
make ext-build   # 打包扩展
```

---

## 5. 知识生命周期

```
RAW ──▶ CANDIDATE ──▶ REVIEW ──▶ VERIFIED ──▶ ARCHIVED
                          └──────▶ REJECTED
                    VERIFIED ⇄ MERGED
```

| 状态 | 含义 |
| --- | --- |
| `CANDIDATE` | Claude 产出、尚未确认，不视为可信知识 |
| `REVIEW` | 与已有知识冲突或需要人工判断 |
| `VERIFIED` | 人工确认，可作为后续编译的可靠上下文 |
| `REJECTED` | 保留记录，不进入默认检索 |
| `MERGED` | 已并入主知识，原条目成为 alias/source |
| `ARCHIVED` | 不进入默认检索，但绝不删除 |

---

## 6. 文档索引

| 文档 | 内容 |
| --- | --- |
| [docs/quickstart-chrome.md](docs/quickstart-chrome.md) | **Chrome 用户照着点就行**（5 分钟，4 步） |
| [docs/usage.md](docs/usage.md) | 完整使用指南：启动 → 加载扩展 → 采集 → 编译 → 写入 → 审核 |
| [docs/architecture.md](docs/architecture.md) | 分层架构、决策记录、数据流 |
| [docs/data-model.md](docs/data-model.md) | Universal Schema、表结构、完整性约束 |
| [docs/api.md](docs/api.md) | REST API 全量契约与错误结构 |
| [docs/adapters.md](docs/adapters.md) | Adapter 接口、selector 管理、fixture 策略 |
| [docs/compiler.md](docs/compiler.md) | 编译流水线、Prompt 版本、Merge Planner |
| [docs/obsidian-vault.md](docs/obsidian-vault.md) | Vault 目录规范、模板、写入与冲突策略 |
| [docs/development.md](docs/development.md) | 本地开发、测试、里程碑 M0→M6 |
| [docs/security.md](docs/security.md) | 威胁模型、密钥处理、数据完整性 |
| [docs/requirements/](docs/requirements/) | 需求设计文档原文 v1.0 |
| [CLAUDE.md](CLAUDE.md) | 交给开发型 AI 的强制约束 |

---

## 7. 当前范围

**已实现（MVP / P0）**：Universal Schema、5 个平台 Adapter、当前 + 历史批量采集、SQLite(+FTS5) 持久化、任务队列与重试、Claude 编译流水线、去重/溯源/合并、Candidate/Verified 审核流、Raw 与 Knowledge 的 Markdown/JSON 导出、Obsidian Vault 原子写入、Side Panel 与设置页。

**P1（未实现）**：Embedding 语义检索、知识图谱导航、更强自动合并、多模型 Provider、附件统一缓存、知识 Diff/回滚、Obsidian 原生插件 UI。

**P2（未实现）**：Agent 主动维护 Vault、MCP Server、知识缺口发现、周期审计、知识衰减检测、多 Vault/多用户。

**明确非目标**：不做 AI 聊天聚合器；不修改第三方站点数据；不自动代用户发消息；不把向量库作为唯一知识存储；不默认删除 Raw 数据。

---

## 8. 安全与隐私

- API Key 只存在于环境变量 / 本地配置，**不进源码、不进 Git**。
- 后端只监听 `127.0.0.1`，写请求需 `X-AKC-Token`，CORS 使用显式来源。
- 原始对话默认本地保存；只有执行编译时才把必要上下文发往 Claude API。
- 日志脱敏：不记录 API Key、Cookie、Authorization 头与完整外发 payload。
- 详见 [docs/security.md](docs/security.md)。

---

## 9. 许可

[MIT](LICENSE)
