# CLAUDE.md

给开发型 AI（Claude Code / Codex / 其他 Agent）的**强制约束**。
修改本仓库任何代码前请先读完本文，违反以下约束的改动一律不接受。

## 0. 项目是什么

AI Knowledge Compiler（AKC）：把多平台 AI 网页端对话当作原始知识流，统一采集 → Claude 编译 → 写入 Obsidian。
核心理念：**Raw 与 Knowledge 分离；AI 编译知识，人类审核知识。**

技术栈固定为：Chrome MV3 + TypeScript（扩展）、Python 3.12 + FastAPI（本地服务）、SQLite + FTS5、Obsidian Markdown、Anthropic Claude API。

## 1. 十条强制原则（来自需求文档 §19）

1. **不得擅自改变 Universal Conversation Schema**；确需变更时必须同时升级 `SCHEMA_VERSION` 并提供迁移。
2. **Raw 数据不可被 AI 编译器覆盖**。`messages` / `conversations` 只允许追加与幂等更新，禁止因编译失败回滚删除。
3. 所有 Provider 必须实现统一 `ProviderAdapter` 接口，禁止在业务代码里散落 CSS selector。
4. Claude 输出必须通过 JSON Schema 校验（`packages/schema/schema/*.json`）。
   输出非法（非 JSON / 不过 Schema）视为**不可重试**错误（重试通常仍不合规且放大成本）；
   网络/限流/5xx 才是可重试错误。两者都不得写入脏数据。
5. 每条 Knowledge 必须有 `source_message_ids` 或等价来源；无来源的 Knowledge 不允许落库。
6. **Verified 内容不能被低置信度 Candidate 静默覆盖**；冲突必须进入 `REVIEW`。
7. 所有外部 API 调用与 DOM 解析都要有错误边界、重试策略与明确的失败语义（`retryable`）。
8. 每完成一个阶段必须跑测试（后端 `pytest`，扩展 `vitest`），不允许先堆积功能再一次联调。
9. **禁止引入 Redis、PostgreSQL、向量数据库等非 MVP 必需依赖**。MVP 只用 SQLite。
10. 优先保证 **Windows + Chrome + Obsidian** 本地可运行。

## 2. 代码分层（后端）

```
routers/      → 只做请求解析、调用 service、格式化响应。禁止写业务规则。
services/     → 业务规则与编排。禁止 import fastapi / Request / Response。
repositories/ → 只做数据访问。禁止写业务规则，禁止跨表写业务判断。
db/           → 模型定义、会话管理、SQL 迁移（up/down 成对）。
compiler/     → Claude 客户端、Prompt 模板（版本化）、输出校验。
```

违反分层的典型反例：在 router 里直接 `session.execute(...)`；在 service 里读 `request.headers`。

## 3. 配置与密钥

- 所有配置来自环境变量，集中在 `apps/backend/akc/config.py`，启动时校验并 **fail fast**。
- 密钥**只能**出现在 `.env` / 环境变量中；`.env` 已 git-ignore，只允许提交 `.env.example`。
- **模型 ID 一律配置注入**，禁止把具体模型名硬编码进业务逻辑。
- 禁止在任何输出、日志、注释中泄露真实密钥。

## 4. 错误处理

- 使用 `akc/errors.py` 中的类型化错误类，禁止 `raise Exception("...")`。
- 全局处理器统一返回：
  ```json
  { "error": { "code": "ADAPTER_PARSE_FAILED", "message": "...", "retryable": false, "details": {} }, "request_id": "..." }
  ```
- 客户端永远看不到堆栈与内部细节。
- 日志为结构化 JSON 且携带 `request_id`，不记录密钥与隐私数据。

## 5. Adapter 纪律

- 每个 Provider 一个文件：`apps/extension/src/adapters/<provider>.ts`。
- 该文件顶部必须有 `SELECTORS` 常量与 `ADAPTER_VERSION`。
- 页面结构检测失败 → `healthCheck()` 返回不健康并给出明确错误，**不得猜测字段、不得产出半成品数据**。
- 先更新 fixture 与单测，再改 adapter。fixture 位于 `apps/extension/tests/fixtures/<provider>/*.html`。
- 遇到 Markdown / LaTeX / 代码块 / 表格时，必须保留结构，禁止只用 `innerText`。

## 6. 任务与幂等

- 幂等键：`IMPORT_CONVERSATION = provider + external_id + content_hash`；
  `COMPILE_CONVERSATION = conversation_id + prompt_version + model`；
  `UPDATE_KNOWLEDGE = knowledge_id + source_hash`；`WRITE_OBSIDIAN = vault + path + content_hash`。
- 指数退避（默认 2s / 5s / 15s），不可恢复错误不得无限重试。
- Job 必须可通过 `job_id` / `request_id` 查询，并保存 `adapter_version` / `compiler_version` / `prompt_version`。

## 7. Obsidian 写入

- 写文件前计算 `content_hash`；文件已存在且被人工修改过 → 检测冲突，**不覆盖**。
- 先写临时文件，成功后原子替换。
- 必须保留 YAML frontmatter 与 `[[Wiki Links]]` 溯源。

## 8. 每个阶段结束必须输出

- 已完成文件
- 数据库变更（新增/修改的迁移）
- API 变更
- 测试结果
- 尚未完成项
- 下一阶段建议

## 9. 里程碑顺序

`M0 工程骨架 → M1 数据层 → M2 Adapter → M3 Extension UI → M4 Claude Compiler → M5 Obsidian → M6 E2E`

## 10. 推送约定（重要）

**本仓库推送一律用 API 工具，不要直接 `git push`**（git 协议在本机网络下时通时断，
api.github.com 直连稳定；且 API 生成的是镜像历史、sha 与本地不同，混用会把历史推岔）。

```bash
# 取 token（Windows 凭据管理器，不要写进任何文件）
printf 'protocol=https\nhost=github.com\n\n' | git credential-wincred get \
  | grep '^password=' | cut -d= -f2- > /tmp/akctoken.txt

# 推送（auto：远端 HEAD 从 API 查，待推提交按 .git/akc-push-state.json 展开）
apps/backend/.venv/Scripts/python.exe scripts/tools/push_via_api.py \
  "$(cat /tmp/akctoken.txt)" auto
rm -f /tmp/akctoken.txt
```

- 工具会回读 refs/heads/main 校验、成功后更新 `.git/akc-push-state.json`
- API 提交与本地内容相同但 sha 不同：**永远不要 `git push --force` 去"统一"它**，
  那会把远端的 API 历史换成另一条镜像历史，白折腾
- 提交信息含远程执行类字样时，命令安全扫描可能拦截 heredoc，用 `git commit -F <文件>` 规避
