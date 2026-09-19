# 架构设计

> 目标：Local-first、Raw 与 Knowledge 分离、AI 可编译 / 人类可审核。
> 本文记录**已经落地**的分层结构与关键决策，不是设想。

## 1. 分层结构

```
Chrome Extension (MV3)                 Local Backend (FastAPI)
┌───────────────────────────┐          ┌──────────────────────────────┐
│ Side Panel / Options UI   │          │ routers/   控制器：解析·格式化 │
│ background  Service Worker│  HTTP    │ services/  业务规则与编排      │
│ content     Adapter 执行  │ ───────► │ repositories/ 数据访问        │
│ shared/     API 客户端     │  :38127  │ compiler/  Claude + 校验      │
└───────────────────────────┘          │ db/        模型 + SQL 迁移     │
                                       └──────────────────────────────┘
```

**依赖方向单向向下**：`routers → services → repositories → db`。
控制器不含业务规则，服务层不 import `fastapi` 的 Request/Response，
因此业务逻辑可以在没有 HTTP 的情况下被单测覆盖（见 `apps/backend/tests/`）。

## 2. 关键决策（含理由）

| 决策 | 选择 | 理由 |
| --- | --- | --- |
| 工程组织 | 按功能分层，而非按技术分层的文件堆 | 改一个功能时改动集中，便于定位与回滚 |
| API 客户端 | 自研类型化 fetch 封装 | 只有 1 个消费方、端点数量有限，引入 React Query / tRPC 属于过度设计 |
| 认证 | 本地随机 token（`X-AKC-Token`）+ 只监听 127.0.0.1 | 浏览器里任意网页都能请求 localhost，仅靠回环地址不够 |
| 实时能力 | 任务状态轮询（1.5s） | MVP 阶段的编译以分钟计，WebSocket 的复杂度不划算 |
| 错误处理 | 类型化 `AppError` + 全局 handler | 客户端只拿到 `{error:{code,message,retryable,details}, request_id}` |
| 队列 | SQLite 表 + 后台单消费者线程 | 不引入 Redis/Postgres；幂等键 + 指数退避已满足 MVP |
| 迁移 | 手写 `*.up.sql` / `*.down.sql` + `schema_migrations` 表 | 可回滚、可 review，且不引入 Alembic 的运行期负担 |
| 前端状态 | 组件内局部状态 | Side Panel 是单页低频交互，不需要全局状态库 |

## 3. 数据流

### 3.1 采集（场景 A）

```
用户点击「保存当前」
  → Side Panel 通过 background 转发 AKC/FETCH_CURRENT
  → content script 执行对应 Provider Adapter（只读 DOM）
  → NormalizedConversation 回传 Side Panel
  → POST /api/v1/conversations/import
  → 后端 normalize + 校验 → 幂等写入 conversations/messages
  → 可选：写 Raw Markdown 到 Vault；可选：入编译队列
```

### 3.2 编译（场景 C）

```
COMPILE_CONVERSATION job
  → Preprocessor（去 UI 噪声、标记来源）
  → Chunker / 上下文预算裁剪
  → Candidate Retriever（FTS5 检索已有知识）
  → Extractor（Claude → JSON → JSON Schema 校验）
  → Merge Planner（create/update/merge/ignore/review 五分支）
  → Knowledge Writer（落库 + 溯源 + 实体）
  → 状态：candidate / review（冲突或低置信度）
```

### 3.3 落库与写入

```
Knowledge ──knowledge_sources──► Message ──► Conversation
     │                                          │
     └──► Obsidian 03_Knowledge/*.md            └──► 01_Raw/<Provider>/*.md
```

## 4. 可观测性

- 结构化 JSON 日志，每条请求带 `request_id`，响应回写 `X-Request-ID`；
- 每次编译写入 `compile_runs`（model / prompt_version / compiler_version / adapter_version / 输入摘要），
  **不记录完整外发 payload**；
- 关键状态变更写入 `audit_logs`；
- 任务可重试性由错误类型决定，失败超过上限进入死信状态（`failed` + `error_code`）。

## 5. 已识别的取舍

- **串行队列**：批量同步 100 条会话时耗时线性增长，但避免了本地 SQLite 写锁竞争；
- **FTS5 而非向量库**：MVP 用关键词检索做 Candidate Retrieval，P1 再叠加 embedding；
- **分支对话**：只保存当前可见主链，完整 branch graph 属 P1。
