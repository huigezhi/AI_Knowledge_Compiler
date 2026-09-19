# 数据模型

## 1. Universal Conversation Schema v1

单一事实来源在 `packages/schema/`：

| 文件 | 作用 |
| --- | --- |
| `src/index.ts` | TypeScript 类型（扩展侧） |
| `src/hash.ts` | 与后端逐字节一致的哈希实现 |
| `schema/universal-conversation.schema.json` | 会话交换格式（JSON Schema draft 2020-12） |
| `schema/compiler-output.schema.json` | Claude 编译输出契约 |

后端用 `jsonschema` 加载同一份 JSON Schema 做校验，
Pydantic 模型位于 `apps/backend/akc/schemas/api.py`。

### Conversation

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 本地主键（`local_<provider>_<external_id>`） |
| `provider` | string | 小写平台标识：`chatgpt` / `claude` / `deepseek` / `doubao` / `zhipu` |
| `provider_conversation_id` | string | 平台侧会话 ID |
| `title` / `url` / `model` | string? | 元信息 |
| `messages` | Message[] | 消息列表（按 sequence 排序） |
| `content_hash` | string | `sha256:<64 hex>` |
| `schema_version` / `adapter_version` | string | 可复现性关键字段 |

### Message / ContentBlock

```ts
type Message = {
  id: string; provider_message_id?: string; conversation_id: string;
  role: "user" | "assistant" | "system" | "tool" | "unknown";
  content: ContentBlock[]; sequence: number; content_hash: string;
  created_at?: string; parent_message_id?: string; model?: string; metadata?: unknown;
}

type ContentBlock =
  | { type: "text"; text: string }
  | { type: "code"; language?: string; text: string }
  | { type: "image"; local_ref?: string; source_url?: string }
  | { type: "file"; local_ref?: string; name?: string; mime?: string }
```

**归一化顺序**：先校验必填与哈希格式 → 再补全派生字段（id / sequence / hash）→ 最后对结果做 Schema 校验。
这样既能在边界拒绝脏数据，又不要求调用方提供服务端统一计算的字段。

## 2. 哈希策略

见 `packages/schema/src/hash.ts` 与 `apps/backend/akc/services/hasher.py`（两者有 golden 对拍测试）：

1. Unicode NFC 归一化
2. 换行统一为 `\n`
3. 去除零宽字符（U+200B/200C/200D/FEFF）
4. 行内连续空格/制表符折叠为单空格
5. 每行两端去空白 → 删除空行 → 整体 trim

**不区分空格数量差异，但保留段落结构。**
`hash_message` 把 `conversation_id + role + sequence + body` 一起计入，
`hash_conversation` 对所有消息的顺序序列做增量摘要。

## 3. 数据库表（`db/migrations/001_init.up.sql`）

| 表 | 关键字段 | 用途 |
| --- | --- | --- |
| `providers` | id, display_name, enabled, adapter_version | 平台注册表 |
| `conversations` | id, provider_id, external_id, title, content_hash, compiled_at | 会话主表 |
| `messages` | id, conversation_id, external_id, role, sequence, content_json, content_hash | 原始消息 |
| `sync_runs` | id, provider_id, status, stats_json | 批量同步批次 |
| `jobs` | id, job_type, idempotency_key, status, attempts, next_run_at | 任务队列 |
| `knowledge` | id, slug, title, status, knowledge_type, markdown, version | 知识实体 |
| `knowledge_sources` | knowledge_id, message_id, conversation_id, relation_type | 知识溯源 |
| `entities` / `relations` | id, name, type, canonical_name / source→relation→target | 实体与关系 |
| `knowledge_links` | knowledge_id, related_knowledge_id, link_type, confidence | 知识关联 |
| `compile_runs` | conversation_id, model, prompt_version, compiler_version, input_digest | 编译留痕 |
| `settings` | key, value_json | 运行时可写配置 |
| `audit_logs` | event_type, entity_type, entity_id, detail_json | 审计 |
| `schema_migrations` | version, applied_at | 迁移进度 |

### 完整性约束

- `conversations(provider_id, external_id)` 唯一；
- `messages(conversation_id, external_id)` 唯一 —— 缺 `provider_message_id` 时用
  `<conversation_id>:<message id>` 兜底（**不能用内容哈希**，否则内容一变就被当成新消息）；
- `jobs(idempotency_key)` 唯一，保证重复入队不重复执行；
- Raw Message 永不因编译失败而删除；
- Knowledge 每次内容更新 `version += 1`，便于回滚。

## 4. FTS5（`002_fts.up.sql`）

- `messages_fts` / `knowledge_fts` 为外部内容表（external content table），
  通过触发器与源表同步；
- 降级环境（SQLite 未编译 FTS5）跳过该迁移，检索退化为主表 `LIKE` 查询，
  由 `services/search.py` 统一处理。

## 5. 知识状态机

```
candidate ──► review ──► verified ──► archived
    │            │            │
    └──► rejected│◄──────────┘
                 └──► merged ──► (unmerge) ──► verified
```

非法转换会返回 `409 Conflict` 并给出允许的目标状态，
`merged` 可通过 `POST /api/v1/knowledge/{id}/unmerge` 撤销。
