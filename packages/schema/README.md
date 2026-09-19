# @akc/schema

Universal Conversation Schema 与编译器输出契约的**单一事实来源**。

## 包含什么

| 文件 | 作用 |
| --- | --- |
| `src/index.ts` | TypeScript 类型：`Conversation` / `Message` / `ContentBlock` / `ProviderAdapter` / 知识 taxonomy 与状态枚举 |
| `src/hash.ts` | 与后端逐字节一致的哈希策略（`normalizeForHash` / `sha256Hex` / `contentHash`） |
| `schema/universal-conversation.schema.json` | 会话交换格式 JSON Schema（draft 2020-12） |
| `schema/compiler-output.schema.json` | Claude 编译输出 JSON Schema（扩展与后端共用同一份校验） |

## 使用

```ts
import type { Conversation, Message } from "@akc/schema";
import { contentHash } from "@akc/schema/hash";
```

后端（Python）在启动时加载 `schema/*.json`，用 `jsonschema` 校验导入请求与 Claude 输出：
`apps/backend/akc/compiler/validator.py`。

## 同步规则（重要）

三处定义必须保持一致：

1. `packages/schema/src/index.ts`（TS 类型）
2. `packages/schema/schema/*.json`（JSON Schema）
3. `apps/backend/akc/schemas/*.py`（Pydantic 模型）

变更任何一处都意味着 **Schema 版本变更**，必须同步升级 `SCHEMA_VERSION`、
更新数据库迁移，并在 `tests/` 中补充用例。详见根目录 `CLAUDE.md` 第 1 条。

## 哈希策略

见 `src/hash.ts` 顶部注释。要点：NFC 归一化 → 换行统一 → 去零宽 → 行内空格折叠 → 去空行。
**不区分空格数量差异，但保留段落结构**。后端 `hasher.py` 有对应实现与对拍测试。
