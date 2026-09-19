# 后端 API

Base URL：`http://127.0.0.1:38127/api/v1`（只监听回环地址）

## 认证与安全

- **写请求**（POST / PUT / DELETE）必须带 `X-AKC-Token`，值与后端 `data/auth_token` 一致；
- 未配置令牌时（开发环境）跳过校验；
- CORS 使用 `AKC_CORS_ORIGINS` 显式来源，生产禁止通配符；
- 所有响应带 `X-Request-ID`。

## 错误契约

```json
{
  "error": {
    "code": "SCHEMA_VALIDATION_FAILED",
    "message": "Human readable message",
    "retryable": false,
    "details": {}
  },
  "request_id": "..."
}
```

| code | HTTP | 含义 | 可重试 |
| --- | --- | --- | --- |
| `BAD_REQUEST` | 400 | 参数缺失或非法 | 否 |
| `UNAUTHORIZED` | 401 | 缺少或错误的 `X-AKC-Token` | 否 |
| `NOT_FOUND` | 404 | 资源不存在 | 否 |
| `SCHEMA_VALIDATION_FAILED` | 422 | 不符合 Universal Conversation Schema / CompilerOutput | 否 |
| `CONFLICT` | 409 | 非法状态转换 / 目标文件冲突 | 否 |
| `ADAPTER_PARSE_FAILED` | 422 | 页面结构解析失败（也用于扩展侧错误映射） | 否 |
| `OBSIDIAN_VAULT_NOT_CONFIGURED` | 400 | 未配置 Vault 路径 | 否 |
| `OBSIDIAN_CONFLICT` | 409 | 目标文件非 AKC 生成，拒绝覆盖 | 否 |
| `CLAUDE_REQUEST_FAILED` | 502 | Claude API 调用失败（网络/限流可重试） | 视情况 |
| `CLAUDE_OUTPUT_INVALID` | 502 | 输出非法 JSON 或未通过 Schema | 否 |
| `JOB_NOT_RUNNABLE` | 500 | 任务类型未注册 | 否 |
| `INTERNAL` | 500 / 503 | 其它内部错误 | 是 |

---

## 端点

### `GET /health`

```json
{ "status": "ok", "service": "akc-backend", "version": "0.1.0",
  "compiler_version": "0.1.0", "schema_version": "1.0.0", "env": "development" }
```

### `GET /ready`

配置自检；不可用返回 503 + `problems` 列表。

### `GET /providers`

返回 5 个平台：`id` / `display_name` / `adapter_version` / `origins` / `capabilities` / `enabled`。

### `POST /conversations/import`

```jsonc
// request
{
  "conversation": { /* UniversalConversation */ },
  "options": { "write_raw_to_obsidian": true, "compile": false }
}
// response
{
  "conversation_id": "local_deepseek_ext-1",
  "created": false,
  "created_messages": 0,
  "updated_messages": 3,
  "content_hash": "sha256:...",
  "obsidian_path": "E:/vault/01_Raw/DeepSeek/xxx.md",
  "job_id": null,
  "warnings": []
}
```

幂等：相同 `(provider, external_id)` 只更新；`content_hash` 未变的消息跳过。

### `GET /conversations`

参数：`provider` / `q` / `limit` / `offset`。返回 `{items, total, limit, offset}`。

### `GET /conversations/{id}`

返回带 `messages` 的会话。

### `GET /conversations/{id}/export`

参数 `fmt=markdown|json`，返回 `{format, media_type, content}`。

### `POST /jobs/compile`

```jsonc
// request
{ "conversation_id": "local_deepseek_ext-1", "idempotency_key": "optional" }
// response（幂等键 = conversation_id + prompt_version + model）
{ "id": "job_xxx", "status": "pending", "job_type": "COMPILE_CONVERSATION", "enqueued": true }
```

### `GET /jobs/{id}` · `GET /jobs` · `POST /jobs/{id}/cancel`

任务视图包含 `status` / `attempts` / `max_attempts` / `stage` / `error` / `result`。

### `GET /knowledge`

参数：`status` / `knowledge_type` / `q` / `include_inactive` / `limit` / `offset`。
返回项带 `source_message_ids`（溯源）。

### `GET /knowledge/search`

`q` 走 FTS5，按 `bm25` 排序。

### `POST /knowledge/{id}/review`

```jsonc
{ "action": "verify", "reason": "" }   // verify | reject | archive | review
```

非法状态转换 → 409。

### `POST /knowledge/{id}/merge` · `POST /knowledge/{id}/unmerge`

```jsonc
{ "target_knowledge_id": "k_001", "reason": "同一知识点的不同表述" }
```

合并会把来源迁移到主知识，并把被合并项标记为 `merged`（`unmerge` 可撤销）。

### `GET /obsidian/status` · `POST /obsidian/sync`

```jsonc
// request
{ "knowledge_ids": ["k_001"], "conversation_ids": [], "include_raw": false }
// response
{ "written": [{ "id": "k_001", "path": "...", "changed": true }],
  "skipped": [{ "id": "k_002", "reason": "refusing to overwrite..." }],
  "vault_path": "E:/vault" }
```

写入策略：内容未变则不落盘；目标文件非 AKC 生成则拒绝覆盖（见 `obsidian-vault.md`）。

### `GET /settings` · `PUT /settings`

```jsonc
// PUT
{ "values": { "vault_raw_folder": "01_Raw" } }
// response
{ "updated": ["vault_raw_folder"], "rejected": [] }
```

白名单外的键（如 `claude_api_key`）会被拒绝，密钥只能通过环境变量注入。

### `POST /sync-runs` · `POST /sync-runs/{id}/finish` · `GET /sync-runs`

批量同步批次：开始 → 逐条导入 → 结束（成功/失败计数与错误原因）。
