# Obsidian Vault 规范

## 1. 目录结构

```
<Vault>/
├── 00_System/            # 配置与 Prompt 模板（可选）
├── 01_Raw/
│   ├── ChatGPT/  Claude/  DeepSeek/  Doubao/  Zhipu/
├── 02_Inbox/
├── 03_Knowledge/
│   ├── Concepts/  Methods/  Technologies/  Projects/  Markets/  Decisions/
├── 04_Index/
└── Attachments/
```

目录名由 `settings.vault_*_folder` 与 `services/obsidian.py#VaultLayout` 决定，
可在 `.env` 中调整。

## 2. Raw 模板（01_Raw）

```markdown
---
type: raw_chat
provider: deepseek
conversation_id: "ext-1"
title: "SQL 性能优化"
created_at: 2026-09-18T20:31:00+08:00
updated_at: 2026-09-18T21:10:00+08:00
content_hash: "sha256:..."
schema_version: 1.0.0
adapter_version: 0.1.0
akc_content_hash: <文件指纹>
---

# SQL 性能优化

## User
...

## Assistant
...
```

文件名：`<slug(标题)>-<YYYY-MM-DD>.md`。

## 3. Knowledge 模板（03_Knowledge）

```markdown
---
type: knowledge
knowledge_type: method
status: candidate
confidence: 0.86
version: 1
topics:
  - "SQL"
entities:
  - "SQL Server"
sources:
  - "[[DeepSeek - SQL性能优化 - 2026-09-18]]"
created_at: 2026-09-18T21:30:00+08:00
updated_at: 2026-09-18T21:30:00+08:00
compiler: Claude
prompt_version: extractor-v1
model: <configured-model-id>
akc_content_hash: <文件指纹>
---

# SQL 查询性能优化方法

## 核心结论
...

## 方法
1. ...

## 风险与例外
...

## 来源证据
- [[DeepSeek - SQL性能优化 - 2026-09-18]]
```

## 4. 写入策略（需求文档 §18.3）

| 规则 | 实现 |
| --- | --- |
| 写前计算 `content_hash` | `services/obsidian.py#content_hash_of` |
| 内容未变化则不落盘 | `write_markdown` 返回 `changed=False` |
| 非 AKC 生成的文件**绝不覆盖** | frontmatter 无 `akc_content_hash` → `OBSIDIAN_CONFLICT` |
| 原子替换 | 临时文件 `.akc-*.tmp` → `os.replace`，失败可重试 |
| 保留 compiler metadata | `prompt_version` / `model` / `version` / `compiler` |
| 冲突可人工处理 | 冲突条目进入响应 `skipped[]`，UI 提示原因 |

**双向关联**：

- Raw → Knowledge：Knowledge 的 `sources` 里写 `[[Wiki Link]]`；
- Knowledge → Knowledge：`knowledge_links` 表 + `[[Wiki Links]]`；
- Merged 条目：保留 `superseded_by` 与 `merged_from` 链接，不做物理删除。

## 5. 使用方式

1. 后端 `.env` 设置 `AKC_VAULT_PATH=<你的 Vault 绝对路径>`；
2. 导入会话时 `write_raw_to_obsidian: true` 即写入 `01_Raw`；
3. 编译后在 Side Panel 点「写入 Obsidian」，或调用
   `POST /api/v1/obsidian/sync` 传入 `knowledge_ids` / `conversation_ids`；
4. 在 Obsidian 里用 Dataview / 图谱查看 `sources` 与 `entities` 形成的网络。

> AKC 与官方 Web Clipper 互不冲突，可以并存；前者负责「会话 → 知识编译」，
> 后者负责网页剪藏。
