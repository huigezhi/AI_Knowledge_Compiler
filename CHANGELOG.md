# Changelog

本项目所有变更遵循 [Keep a Changelog](https://keepachangelog.com/) 风格，版本号暂遵循 `0.x` 迭代。

## [Unreleased]

### Added
- 初始 MVP 实现，覆盖需求文档 v1.0 的 P0 范围，里程碑 M0 → M6。
- **M0 工程骨架**：monorepo 结构、CI、`.editorconfig`、`.env.example`、`CLAUDE.md`、SQL 迁移框架。
- **M1 数据层**：Universal Conversation Schema v1（TS + JSON Schema + Pydantic）、13 张核心表、FTS5 检索、仓储层、类型化错误体系、结构化日志、配置校验。
- **M2 Adapter**：ChatGPT / Claude / DeepSeek / 豆包 / 智谱清言 五个适配器，统一 `ProviderAdapter` 接口，selector 常量集中管理，每平台 6 类回归 fixture。
- **M3 Extension UI**：Chrome MV3 Side Panel、Options 设置页、Background Service Worker、Content Script、类型化 API 客户端（重试 / 错误映射 / 离线提示）。
- **M4 Compiler**：Preprocessor → Chunker → Candidate Retriever → Extractor → Dedup → Contradiction → Merge Planner 流水线，Prompt 版本化，JSON Schema 校验，任务队列（指数退避 + 死信状态）。
- **M5 Obsidian**：Raw 与 Knowledge Markdown 模板、YAML frontmatter、`[[Wiki Links]]` 溯源、临时文件 + 原子替换、人工修改冲突检测；Candidate/Verified 审核与合并 API。

### Added
- **使用指南** `docs/usage.md`：启动 → 配置 → 加载扩展 → 填令牌 → 采集 → 编译 → 写入 → 审核 → 排查，
  全部命令均在本机实测通过。

### Fixed
- **本地令牌此前并未真正生效**：`ensure_auth_token()` 实现了却从未在启动时调用，写请求处于无保护状态。
  现已在 lifespan 中调用，只记录令牌文件路径、不记录令牌值。
- **令牌校验位置错误**：校验原本写在 HTTP 中间件里，异常无法被全局处理器捕获会退化成 500。
  改为 FastAPI 应用级依赖 `dependencies=[Depends(require_token)]`，非法请求规范化返回 401。
- **扩展缺失 content script**：`package.json` 的 `build` 只跑了主 vite 配置，`dist` 中没有 `content.js`，
  加载扩展后无法注入任何平台页面。已补齐第二个构建步骤并校验 manifest 引用齐全。

### Security
- 本地服务只监听 `127.0.0.1`，写请求强制 `X-AKC-Token`，CORS 显式来源。
- API Key 仅从环境变量读取，`.env` 已 git-ignore，日志脱敏。
- 令牌启动时生成并持久化到 `data/auth_token`（权限 600），只读端点免令牌不影响扩展首屏探测。

### Known limitations
- Embedding 语义检索、知识图谱、多模型 Provider、附件缓存、知识 Diff 回滚属于 P1，未实现。
- 分支对话仅保存当前可见主链，完整 branch graph 属于 P1。
