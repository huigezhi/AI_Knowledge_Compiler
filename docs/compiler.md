# Claude Knowledge Compiler

> 编译 ≠ 摘要。系统输出的是**可复用、可溯源、可审核**的知识。

## 1. 流水线

```
Raw Conversation
  ↓ Preprocessor     去 UI 噪声，保留代码/表格/引用，标记来源消息 ID
  ↓ Chunker          按 max_context_tokens 裁剪（超出时显式标注 truncated）
  ↓ Candidate Retrieval  FTS5 检索已有知识，作为 <related_knowledge> 注入
  ↓ Extractor        Claude → JSON → **必须通过 JSON Schema 校验**
  ↓ Merge Planner    create / update / merge / ignore / review 五分支
  ↓ Knowledge Writer 落库 + knowledge_sources 溯源 + entities
  ↓ Review Queue     candidate（可信）或 review（冲突/低置信度）
  ↓ Obsidian Writer  03_Knowledge/**.md（原子写入，人工修改不覆盖）
```

实现位置：
`services/compile_service.py`（编排）、`compiler/extractor.py`（提取与收敛）、
`services/merge_planner.py`（五分支判定）、`compiler/client.py`（API 调用与错误分类）、
`compiler/prompts.py`（版本化模板）、`compiler/validator.py`（Schema 校验）。

## 2. Taxonomy（需求文档 §8.2）

`fact` / `concept` / `method` / `heuristic` / `decision` / `question` / `hypothesis` / `opinion`

**硬约束**：

- 不得把 `opinion`、`hypothesis` 自动升级为 `fact`；
- 无来源支撑的内容只能标记为 `hypothesis` / `question` / `opinion`，且 `needs_verification = true`；
- **每条知识必须至少引用一条真实存在的 `source_message_ids`**，否则丢弃；
- 置信度低于 0.6 或 `needs_verification` 为真时进入 `review`。

## 3. Merge Planner 判定规则

| 条件 | 动作 |
| --- | --- |
| 候选类型为 `opinion` / `question` | `ignore`（不进主知识库） |
| 相似度 < 0.45 | `create` |
| 类型不同（如 method vs fact） | `review` + `knowledge_type` 冲突 |
| 相似度 ≥ 0.72 且证据相同 | `ignore`（纯重复） |
| 相似度 ≥ 0.72、证据不同，但已有条目为 `verified` 且正文实质不同 | `review`（**禁止静默覆盖 verified**） |
| 相似度 ≥ 0.72、证据不同 | `merge`（合并来源，保留主知识） |
| 0.30 ≤ 相似度 < 0.72 且已有条目为 `verified` | `review` |
| 0.30 ≤ 相似度 < 0.72 | `update`（补充细节，`version += 1`） |

相似度基于**字符 bigram 的 Jaccard 系数**，中英文通用；
整体相似度取 `max(标题相似度, (标题相似度 + 正文相似度) / 2)`。

## 4. Prompt 与模型

- Prompt 版本常量：`EXTRACTOR_PROMPT_VERSION = "extractor-v1"`、
  `MERGE_PLANNER_PROMPT_VERSION = "merge-planner-v1"`，写入 `compile_runs` 与笔记 frontmatter；
- **模型 ID 一律由配置注入**（`AKC_CLAUDE_MODEL`），代码中不存在硬编码的模型名；
- 上下文预算由 `AKC_CLAUDE_MAX_CONTEXT_TOKENS` 换算；
- 每次调用记录 `model / prompt_version / compiler_version / adapter_version / input_digest`，
  **不记录完整外发 payload**。

## 5. 错误分类

| 情况 | 错误 | 重试 |
| --- | --- | --- |
| 网络超时 / 传输错误 | `ClaudeRequestError(retryable=True)` | 是（指数退避） |
| 429 / 5xx | 同上 | 是 |
| 401 / 403 / 其它 4xx | `ClaudeRequestError(retryable=False)` | 否 |
| 输出不是 JSON 或不过 Schema | `ClaudeOutputInvalidError` | 否 |

**Raw 数据在任何编译失败下都不受影响**——编译只是会话的一个后置阶段，
失败时 job 进入 `failed` 并可在 UI 里重试。

## 6. 测试

`apps/backend/tests/test_compile_pipeline.py` 用 `httpx.MockTransport` 构造假 Claude 响应，
覆盖：Schema 校验、fenced JSON 解析、5xx 可重试、401 不可重试、
无来源条目被丢弃、端到端导入→编译→溯源。
