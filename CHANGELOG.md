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

### Security
- 本地服务只监听 `127.0.0.1`，写请求强制 `X-AKC-Token`，CORS 显式来源。
- API Key 仅从环境变量读取，`.env` 已 git-ignore，日志脱敏。

### Known limitations
- Embedding 语义检索、知识图谱、多模型 Provider、附件缓存、知识 Diff 回滚属于 P1，未实现。
- 分支对话仅保存当前可见主链，完整 branch graph 属于 P1。
