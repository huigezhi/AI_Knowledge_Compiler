# AI Knowledge Compiler（AKC）详细需求设计文档 v1.0
> 用途：直接交给 Claude Code / Codex / 其他开发型 AI 实现。
AI Knowledge Compiler
多平台 AI 对话采集、Claude 知识编译与 Obsidian 知识库系统
| 项目 | 内容 |
| --- | --- |
| 文档类型 | PRD + 系统架构设计 + 技术规格 + 验收标准 |
| 版本 | v1.0 |
| 目标 | 直接交给开发型 AI 实现 MVP，并可继续迭代至生产版 |
| 首选形态 | Chrome Extension + 本地服务 + Obsidian Vault + Claude API |
| 核心理念 | Raw 与 Knowledge 分离；AI 编译知识，人类审核知识 |

说明：本文件不是营销型产品文案，而是开发约束文档。实现过程中，开发 AI 应优先遵循“必须实现/验收标准”，不要自行改变核心数据模型和知识生命周期。

## 0. 文档导航
- 1. 产品定义与目标
- 2. 用户场景与核心工作流
- 3. 范围、优先级与非目标
- 4. 总体架构
- 5. 数据模型与数据库设计
- 6. Chrome Extension 设计
- 7. 多平台 Provider Adapter 设计
- 8. Claude Knowledge Compiler 设计
- 9. Prompt 与结构化输出规范
- 10. Obsidian 知识库规范
- 11. 后端 API 设计
- 12. 本地运行与部署
- 13. 安全、隐私与数据完整性
- 14. UI/UX 设计要求
- 15. 任务队列、重试与可观测性
- 16. 测试与验收标准
- 17. 开发里程碑
- 18. 风险与兼容性策略
- 19. 给开发型 AI 的实施指令
- 20. 附录：示例 Schema 与模板

## 1. 产品定义与目标
产品名称：AI Knowledge Compiler（简称 AKC）。定位不是“AI 聊天导出器”，而是“AI 对话知识编译器”：把用户在 ChatGPT、Claude、DeepSeek、豆包、智谱清言等网页端产生的对话作为原始知识流，统一采集、存档、分析、去重、关联、提炼，并将稳定知识写入 Obsidian。

### 1.1 核心价值
- 跨平台统一：不同 AI 平台进入同一 Universal Conversation Schema。
- 原始数据永久可追溯：Raw Chat 不允许被知识编译过程覆盖。
- 知识而非摘要：系统输出的是可复用概念、方法、事实、经验、决策和待验证命题。
- 跨对话合并：能够发现“不同 AI / 不同日期 / 不同主题”的相同知识，并建议合并。
- 人机协作：Claude 提炼，人负责最终确认；Candidate 与 Verified 分离。
- Obsidian 原生友好：所有最终知识为 Markdown + YAML Properties + Wiki Links。
- Local-first：原始聊天、数据库、Obsidian Vault 默认保存在本地；外部 AI API 仅在用户触发编译时接收必要上下文。

### 1.2 成功标准
| 指标 | MVP目标 |
| --- | --- |
| 平台覆盖 | 至少 5 个：ChatGPT、Claude、DeepSeek、豆包、智谱清言；架构可扩展。 |
| 采集可靠性 | 对支持平台的常见会话成功采集率 >= 95%（测试夹具环境）。 |
| 去重 | 相同 message_id 或 content_hash 不产生重复记录。 |
| 知识提炼 | 一次对话可以生成 0~N 个结构化知识 Candidate。 |
| 知识溯源 | 每条 Knowledge 必须可回溯到至少一个 Raw Message。 |
| Obsidian写入 | 能创建/更新 Markdown，并保留 YAML frontmatter。 |
| 失败恢复 | 网络/API/页面结构异常不丢原始数据；任务可重试。 |


## 2. 用户场景与核心工作流

### 2.1 场景 A：保存当前对话
```text
浏览器打开 DeepSeek 对话
```
```text
→ 点击 AKC Side Panel
```
```text
→ 选择“保存当前对话”
```
```text
→ Provider Adapter 提取会话
```
```text
→ 标准化
```
```text
→ SQLite 写入 Raw Conversation / Raw Message
```
```text
→ 可选：立即进入 Claude 编译队列
```

### 2.2 场景 B：批量同步历史会话
```text
进入平台历史会话列表
```
```text
→ 获取会话索引
```
```text
→ 用户勾选/全选
```
```text
→ 分页/逐会话抓取
```
```text
→ 增量判断
```
```text
→ 成功/失败计数
```
```text
→ 生成同步报告
```

### 2.3 场景 C：知识编译
```text
Raw Conversation
```
```text
→ 文本清洗与分块
```
```text
→ Candidate Retrieval：检索相关已有知识
```
```text
→ Claude Extractor
```
```text
→ Entity/Relation Extractor
```
```text
→ Duplicate Detector
```
```text
→ Contradiction Detector
```
```text
→ Merge Planner
```
```text
→ Knowledge Writer
```
```text
→ Candidate/Verified 状态管理
```
```text
→ Obsidian Markdown
```

### 2.4 场景 D：跨对话整合
系统必须支持：同一主题的 10~100 条历史对话进入后，Claude 不应机械生成 100 个独立笔记，而应先检索已有知识，再识别重叠、补充与冲突。最终结果允许“一条知识对应多个来源”。

## 3. 范围、优先级与非目标

### 3.1 MVP 必须实现（P0）
- Chrome MV3 Extension + Side Panel
- ChatGPT / Claude / DeepSeek / 豆包 / 智谱清言 Provider Adapter
- 当前对话采集 + 历史批量采集
- Universal Conversation Schema
- SQLite 数据持久化
- Markdown / JSON 导出
- Obsidian Vault 写入
- Claude 编译 Pipeline
- Candidate / Verified 知识状态
- 去重、引用、来源追踪
- 任务队列、失败重试、同步日志
- 基本设置页：Vault、Claude API、模型、编译策略。

### 3.2 P1
- Embedding + 语义相似搜索
- Knowledge Graph 辅助导航
- 更强的自动合并
- 多模型 Provider（Gemini/Kimi/Qwen 等）
- 附件/图片/代码块统一缓存
- 可选本地模型用于低成本预处理
- 知识变更 Diff 与回滚
- Obsidian 插件原生 UI。

### 3.3 P2
- Agent 主动维护整个 Vault
- MCP Server
- 自动发现知识缺口
- 周期性知识审计
- 知识衰减/过期检测
- 多 Vault / 多用户 / NAS 同步。

### 3.4 明确非目标
- 不做 AI Chat 聚合器：不负责在 AKC 内重新实现多个 AI 聊天窗口。
- 不修改第三方网站数据，不自动发送用户消息。
- 不把 Vector DB 作为唯一知识存储。
- 不默认删除 Raw 数据。
- 不强制使用 Obsidian 官方 Web Clipper；AKC 是独立系统，可与其并存。

## 4. 总体架构
```text
┌─────────────────────────────────────────────┐
```
```text
│                 Chrome Extension             │
```
```text
│ Side Panel / Popup / Content Script / Adapter│
```
```text
└───────────────────┬─────────────────────────┘
```
```text
│ localhost HTTP/WebSocket
```
```text
▼
```
```text
┌─────────────────────────────────────────────┐
```
```text
│                Local Backend                 │
```
```text
│ FastAPI / Service Layer / Job Queue         │
```
```text
├─────────────────────────────────────────────┤
```
```text
│ Conversation Normalizer                     │
```
```text
│ Claude Compiler                             │
```
```text
│ Search / Similarity / Dedup                 │
```
```text
│ Obsidian Writer                             │
```
```text
│ Audit / Logs / Config                       │
```
```text
└───────────────┬───────────┬─────────────────┘
```
```text
│           │
```
```text
▼           ▼
```
```text
┌──────────┐   ┌──────────────┐
```
```text
│ SQLite   │   │ Obsidian Vault│
```
```text
│ Raw/Meta │   │ Markdown      │
```
```text
└──────────┘   └──────────────┘
```
```text
│
```
```text
▼
```
```text
┌───────────────┐
```
```text
│ Claude API     │
```
```text
│ Extract/Merge  │
```
```text
└───────────────┘
```

### 4.1 技术栈建议
| 层 | 建议 | 说明 |
| --- | --- | --- |
| 浏览器 | TypeScript + Chrome MV3 + Side Panel | Adapter 可插件化。 |
| 前端构建 | Vite/WXT | 优先选择维护活跃、便于多入口构建的方案。 |
| 后端 | Python 3.12+ + FastAPI | 便于 AI/数据处理与本地部署。 |
| 数据库 | SQLite + FTS5 | MVP 足够；后续可加向量索引。 |
| ORM | SQLModel/SQLAlchemy | 二选一，保持迁移能力。 |
| 队列 | MVP SQLite job queue；P1 可 Redis | 避免引入不必要的基础设施。 |
| AI | Anthropic Claude API | 采用 Messages + Tool Use/结构化输出能力。 |
| Embedding | P1 可选本地/云端模型 | 不要阻塞 MVP。 |
| Obsidian | 直接写 Vault Markdown | 避免绑定特定插件 API。 |
| 测试 | Vitest/Playwright + Pytest | Adapter 和后端均需自动化测试。 |


## 5. 数据模型与数据库设计

### 5.1 Universal Conversation Schema
```text
type Conversation = {
```
```text
id: string;
```
```text
provider: string;
```
```text
provider_conversation_id: string;
```
```text
title: string;
```
```text
url?: string;
```
```text
model?: string;
```
```text
created_at?: string;
```
```text
updated_at?: string;
```
```text
tags?: string[];
```
```text
messages: Message[];
```
```text
raw_payload_ref?: string;
```
```text
content_hash: string;
```
```text
};
```
```text
type Message = {
```
```text
id: string;
```
```text
provider_message_id?: string;
```
```text
conversation_id: string;
```
```text
role: "user" | "assistant" | "system" | "tool" | "unknown";
```
```text
content: ContentBlock[];
```
```text
sequence: number;
```
```text
created_at?: string;
```
```text
parent_message_id?: string;
```
```text
model?: string;
```
```text
metadata?: Record<string, unknown>;
```
```text
content_hash: string;
```
```text
};
```
```text
type ContentBlock =
```
```text
| {type: "text"; text: string}
```
```text
| {type: "code"; language?: string; text: string}
```
```text
| {type: "image"; local_ref?: string; source_url?: string}
```
```text
| {type: "file"; local_ref?: string; name?: string; mime?: string};
```

### 5.2 数据库表
| 表 | 关键字段 | 用途 |
| --- | --- | --- |
| providers | id, name, enabled, adapter_version | 平台适配器注册表 |
| conversations | id, provider_id, external_id, title, url, content_hash, timestamps | 会话主表 |
| messages | id, conversation_id, external_id, role, sequence, content_json, content_hash | 原始消息 |
| sync_runs | id, provider_id, started_at, finished_at, status, stats_json | 同步批次 |
| jobs | id, job_type, payload_json, status, attempts, next_run_at, error | 任务队列 |
| knowledge | id, slug, title, status, category, markdown, content_hash, version | 知识实体 |
| knowledge_sources | knowledge_id, message_id, conversation_id, relation_type | 知识溯源 |
| entities | id, name, type, canonical_name | 实体节点 |
| relations | id, source_entity_id, relation, target_entity_id | 知识关系 |
| knowledge_links | knowledge_id, related_knowledge_id, link_type, confidence | 知识关联 |
| compile_runs | id, conversation_id, model, prompt_version, result_json, status | Claude 编译记录 |
| settings | key, value_json, updated_at | 本地配置 |
| audit_logs | id, event_type, entity_type, entity_id, detail_json, created_at | 审计日志 |


### 5.3 数据完整性约束
- conversation(provider_id, external_id) 唯一。
- message(conversation_id, external_id) 在可获得 provider_message_id 时唯一。
- content_hash 用于二次幂等；哈希建议 SHA-256。
- Raw Message 永不因编译失败而删除。
- Knowledge 更新采用 version 或变更记录，支持回滚。

## 6. Chrome Extension 设计

### 6.1 权限原则
- 最小权限原则。只申请读取目标 AI 网站页面和访问 localhost 后端所需权限。
- 不注入第三方站点账号密码，不读取 localStorage/cookies 中与采集无关的密钥。
- 扩展不把原始聊天上传到第三方服务，除非用户点击“编译”，并明确配置 Claude API。

### 6.2 UI 页面
| 界面 | 能力 |
| --- | --- |
| Side Panel | 平台识别、当前会话、历史会话、批量选择、保存、编译、进度。 |
| Settings | 后端地址、API Key、模型、Vault 路径、同步策略、日志等级。 |
| Sync Report | 成功/失败/跳过、错误原因、重试。 |
| Knowledge Preview | Claude 提取出的知识、已有知识命中、合并建议、来源。 |


### 6.3 Extension-Backend 通信
```text
POST /api/v1/conversations/import
```
```text
POST /api/v1/sync-runs
```
```text
POST /api/v1/compile
```
```text
GET  /api/v1/jobs/:id
```
```text
GET  /api/v1/providers
```
```text
GET  /api/v1/settings
```
```text
PUT  /api/v1/settings
```
本地服务默认只监听 127.0.0.1。扩展调用必须带 CSRF/随机本地 token 或等价机制，避免其他网页伪造本地请求。

## 7. 多平台 Provider Adapter 设计

### 7.1 Adapter 接口
```text
interface ProviderAdapter {
```
```text
id: string;
```
```text
matches(url: string): boolean;
```
```text
detectPage(): PageKind;
```
```text
listConversations(options?: ListOptions): Promise<ConversationSummary[]>;
```
```text
fetchConversation(id: string): Promise<NormalizedConversation>;
```
```text
fetchCurrentConversation(): Promise<NormalizedConversation>;
```
```text
healthCheck(): Promise<AdapterHealth>;
```
```text
}
```

### 7.2 平台优先级
| Provider | MVP要求 | 主要风险 |
| --- | --- | --- |
| DeepSeek | 当前/历史/批量 | DOM 变化、虚拟列表 |
| 豆包 | 当前/历史/批量 | React/异步渲染、滚动加载 |
| 智谱清言 | 当前/历史/批量 | 页面结构变化 |
| ChatGPT | 当前/历史 | 动态组件、分支对话 |
| Claude | 当前/历史 | 长消息、代码块、附件 |

实现原则：严禁把 CSS selector 散落在业务代码中。每个 Provider 维护独立 selector 常量、DOM 版本检测、fixture HTML/JSON、adapter_version。页面结构变化后，先更新 fixture 和 adapter 单测，再发布。

### 7.3 采集策略
- 优先读取页面已渲染 DOM；不要尝试绕过平台认证。
- 支持虚拟列表时，采用滚动 + 稳定锚点 + 内容 hash 去重。
- 对话具有分支树时，至少保存当前可见主链；P1 再扩展完整 branch graph。
- 遇到 Markdown、LaTeX、代码块、表格时，必须保持结构，不得只提取 innerText。

## 8. Claude Knowledge Compiler 设计

### 8.1 编译流水线
```text
Raw Conversation
```
```text
↓
```
```text
Preprocessor
```
```text
- 去除 UI 噪声
```
```text
- 保留代码/表格/引用
```
```text
- 标记来源消息 ID
```
```text
↓
```
```text
Chunker
```
```text
↓
```
```text
Candidate Retriever
```
```text
- FTS5
```
```text
- 可选 embedding
```
```text
↓
```
```text
Extractor
```
```text
↓
```
```text
Classifier
```
```text
↓
```
```text
Entity/Relation Extractor
```
```text
↓
```
```text
Duplicate Detector
```
```text
↓
```
```text
Contradiction Detector
```
```text
↓
```
```text
Merge Planner
```
```text
↓
```
```text
Knowledge Writer
```
```text
↓
```
```text
Review Queue
```
```text
↓
```
```text
Obsidian Writer
```

### 8.2 知识类型 taxonomy
| 类型 | 定义 | 示例 |
| --- | --- | --- |
| fact | 可从来源直接支持的陈述 | 某 API 的参数限制 |
| concept | 可长期复用的概念模型 | Predicate Pushdown |
| method | 步骤化方法 | SQL 优化流程 |
| heuristic | 经验规则 | 先看执行计划再改 SQL |
| decision | 用户明确做出的决定 | 项目技术栈决定 |
| question | 尚未解决的问题 | 某指标是否稳定 |
| hypothesis | 待验证假设 | 某变量可能领先指数 |
| opinion | 主观观点 | 作者倾向某技术 |

重要约束：Claude 不得把 opinion、hypothesis 自动升级为 fact；没有来源支撑的内容只能标记为推测或 Candidate。

### 8.3 知识生命周期
```text
RAW
```
```text
→ CANDIDATE
```
```text
→ REVIEW
```
```text
→ VERIFIED
```
```text
↘ REJECTED
```
```text
VERIFIED ↔ MERGED
```
```text
VERIFIED → ARCHIVED
```
| 状态 | 允许行为 |
| --- | --- |
| CANDIDATE | 可修改，不视为可信知识 |
| REVIEW | 等待用户确认/查看差异 |
| VERIFIED | 可作为后续编译的可靠上下文 |
| REJECTED | 保留记录，不进入默认检索 |
| MERGED | 旧条目成为 alias/source，主知识保留 |
| ARCHIVED | 不进入默认检索，但不删除 |


## 9. Prompt 与结构化输出规范

### 9.1 System Prompt 核心规则
```text
You are a Personal Knowledge Compiler.
```
```text
Your job is to compile durable knowledge from AI conversations.
```
```text
Do NOT merely summarize.
```
```text
Preserve source traceability.
```
```text
Separate facts, opinions, assumptions, and hypotheses.
```
```text
Never invent unsupported facts.
```
```text
Prefer merge/update over creating duplicates.
```
```text
When uncertain, output uncertainty explicitly.
```
```text
Return only the requested structured output.
```

### 9.2 Extractor 输入
```text
<conversation>
```
```text
<metadata>...</metadata>
```
```text
<message id="m1" role="user">...</message>
```
```text
<message id="m2" role="assistant">...</message>
```
```text
</conversation>
```
```text
<related_knowledge>...</related_knowledge>
```
```text
<taxonomy>fact, concept, method, heuristic, decision, question, hypothesis, opinion</taxonomy>
```

### 9.3 Extractor 输出 Schema
```text
{
```
```text
"items": [
```
```text
{
```
```text
"title": "string",
```
```text
"type": "fact|concept|method|heuristic|decision|question|hypothesis|opinion",
```
```text
"summary": "string",
```
```text
"body_markdown": "string",
```
```text
"source_message_ids": ["m1", "m2"],
```
```text
"confidence": 0.0,
```
```text
"needs_verification": true,
```
```text
"entities": ["SQL Server", "CTE"],
```
```text
"candidate_existing_knowledge_ids": [],
```
```text
"merge_action": "create|update|merge|ignore|review"
```
```text
}
```
```text
],
```
```text
"entities": [],
```
```text
"relations": [],
```
```text
"contradictions": [],
```
```text
"notes": []
```
```text
}
```

### 9.4 Merge Planner 规则
- 语义相同、证据相同：ignore。
- 语义相同、证据不同：merge。
- 已有知识更完整，新对话提供补充：update。
- 已有知识与新内容冲突：review，不允许自动覆盖 verified 内容。
- 新内容仅为观点或临时问题：单独记录或不入主知识库。

### 9.5 模型分层
| 任务 | 推荐模型策略 |
| --- | --- |
| 轻量分类/去噪 | 低成本、低延迟模型 |
| 知识抽取 | 平衡能力/成本模型 |
| 复杂合并/冲突分析 | 高能力 Claude 模型 |
| 最终写作 | 与抽取模型同级或更高 |
| 用户自定义 | 允许配置模型 ID，不把模型名硬编码 |

不要把具体模型名称写死在业务逻辑。Anthropic 模型会持续迭代，模型名、能力与 API 特性应通过配置注入。

## 10. Obsidian 知识库规范

### 10.1 推荐目录
```text
AI-Knowledge/
```
```text
├── 00_System/
```
```text
│   ├── config.yaml
```
```text
│   └── prompts/
```
```text
├── 01_Raw/
```
```text
│   ├── ChatGPT/
```
```text
│   ├── Claude/
```
```text
│   ├── DeepSeek/
```
```text
│   ├── Doubao/
```
```text
│   └── Zhipu/
```
```text
├── 02_Inbox/
```
```text
├── 03_Knowledge/
```
```text
│   ├── Concepts/
```
```text
│   ├── Methods/
```
```text
│   ├── Technologies/
```
```text
│   ├── Projects/
```
```text
│   ├── Markets/
```
```text
│   └── Decisions/
```
```text
├── 04_Index/
```
```text
└── Attachments/
```

### 10.2 Raw Markdown 模板
```text
---
```
```text
type: raw_chat
```
```text
provider: deepseek
```
```text
conversation_id: "..."
```
```text
title: "SQL 性能优化"
```
```text
created_at: 2026-09-18T20:31:00+08:00
```
```text
updated_at: 2026-09-18T21:10:00+08:00
```
```text
content_hash: "sha256:..."
```
```text
---
```
```text
# SQL 性能优化
```
```text
## User
```
```text
...
```
```text
## Assistant
```
```text
...
```

### 10.3 Knowledge Markdown 模板
```text
---
```
```text
type: knowledge
```
```text
knowledge_type: method
```
```text
status: candidate
```
```text
confidence: 0.86
```
```text
topics:
```
```text
- SQL
```
```text
entities:
```
```text
- SQL Server
```
```text
sources:
```
```text
- "[[DeepSeek - SQL性能优化 - 2026-09-18]]"
```
```text
created_at: 2026-09-18T21:30:00+08:00
```
```text
updated_at: 2026-09-18T21:30:00+08:00
```
```text
compiler: Claude
```
```text
prompt_version: extractor-v1
```
```text
---
```
```text
# SQL 查询性能优化方法
```
```text
## 核心结论
```
```text
...
```
```text
## 方法
```
```text
1. ...
```
```text
## 适用场景
```
```text
...
```
```text
## 风险与例外
```
```text
...
```
```text
## 来源证据
```
```text
- [[DeepSeek - SQL性能优化 - 2026-09-18]]
```

### 10.4 双向关联规则
- Raw → Knowledge：Knowledge 必须保存 source links。
- Knowledge → Knowledge：使用 Obsidian Wiki Links。
- Entity → Knowledge：使用标准 slug，避免同名文件。
- Merged Note：保留 aliases 与 redirect 信息。

## 11. 后端 API 设计
| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /api/v1/health | 后端健康检查 |
| GET | /api/v1/providers | Provider 状态 |
| POST | /api/v1/conversations/import | 导入标准化会话 |
| GET | /api/v1/conversations | 查询会话 |
| GET | /api/v1/conversations/{id} | 读取会话 |
| POST | /api/v1/jobs/compile | 创建编译任务 |
| GET | /api/v1/jobs/{id} | 读取任务状态 |
| GET | /api/v1/knowledge | 检索知识 |
| POST | /api/v1/knowledge/{id}/review | 审核 Candidate |
| POST | /api/v1/knowledge/{id}/merge | 执行合并 |
| POST | /api/v1/obsidian/sync | 写入/更新 Vault |
| GET | /api/v1/settings | 配置读取 |
| PUT | /api/v1/settings | 配置更新 |


### 11.1 Import API 示例
```text
POST /api/v1/conversations/import
```
```text
Content-Type: application/json
```
```text
{
```
```text
"conversation": { ...UniversalConversation... },
```
```text
"options": {
```
```text
"write_raw_to_obsidian": true,
```
```text
"compile": false
```
```text
}
```
```text
}
```
```text
Response
```
```text
{
```
```text
"conversation_id": "local_...",
```
```text
"created": false,
```
```text
"updated_messages": 3,
```
```text
"job_id": null
```
```text
}
```

### 11.2 Error Contract
```text
{
```
```text
"error": {
```
```text
"code": "ADAPTER_PARSE_FAILED",
```
```text
"message": "Human readable message",
```
```text
"retryable": false,
```
```text
"details": {}
```
```text
},
```
```text
"request_id": "..."
```
```text
}
```

## 12. 本地运行与部署

### 12.1 开发环境
```text
Windows 11 / macOS / Linux
```
```text
Node.js 20+
```
```text
Python 3.12+
```
```text
Chrome/Edge Chromium
```
```text
Obsidian
```
```text
Git
```

### 12.2 MVP 运行模式
```text
Chrome Extension
```
```text
↓
```
```text
127.0.0.1:38127
```
```text
↓
```
```text
FastAPI
```
```text
↓
```
```text
SQLite + Obsidian Vault
```
MVP 不要求 VPS。所有核心数据处理尽量本地完成；Claude API 是外部依赖。后续可提供 Docker 模式，但 Docker 不应成为本地桌面用户的必选项。

## 13. 安全、隐私与数据完整性
- API Key 不写入源码、不提交 Git。使用系统凭据存储或本地加密配置；MVP 至少支持环境变量/本地权限受控配置。
- 原始对话默认本地保存。只有执行 Claude 编译时，才把必要上下文发送到 Claude API。
- 编译请求应记录 prompt_version、model、request_id、时间和输入摘要，不默认记录完整外发 payload。
- 任何自动合并必须可撤销；Verified 知识不能被低置信度 Candidate 静默覆盖。
- 所有 destructive action（删除、覆盖、批量合并）必须有明确用户操作或可配置开关。
- 日志不得泄露 API Key、Cookie、Authorization header。

## 14. UI/UX 设计要求

### 14.1 Side Panel 核心布局
```text
┌──────────────────────────────┐
```
```text
│ AKC        [Settings]        │
```
```text
├──────────────────────────────┤
```
```text
│ Provider: DeepSeek            │
```
```text
│ Current: SQL性能优化          │
```
```text
│                              │
```
```text
│ [保存当前] [保存+编译]         │
```
```text
│                              │
```
```text
│ 历史会话                       │
```
```text
│ □ SQL优化                     │
```
```text
│ □ CTE讨论                     │
```
```text
│ □ 索引问题                    │
```
```text
│                              │
```
```text
│ [全选] [批量同步]              │
```
```text
├──────────────────────────────┤
```
```text
│ 编译结果                       │
```
```text
│ 识别 3 个知识                  │
```
```text
│ 命中已有 2 条                  │
```
```text
│ 建议合并 1 条                  │
```
```text
│                              │
```
```text
│ [查看] [写入 Obsidian]         │
```
```text
└──────────────────────────────┘
```

### 14.2 状态与提示
- 同步中：显示当前平台、已处理/总数、成功/失败。
- 编译中：显示阶段（Extract/Link/Merge/Write），不显示虚假的百分比。
- 失败：提供 retry 与查看错误详情。
- 合并：显示 old/new Diff、来源和置信度。

## 15. 任务队列、重试与可观测性
| Job Type | 幂等键 | 默认重试 |
| --- | --- | --- |
| IMPORT_CONVERSATION | provider+external_id+content_hash | 2 |
| COMPILE_CONVERSATION | conversation_id+prompt_version+model | 2 |
| UPDATE_KNOWLEDGE | knowledge_id+source_hash | 1 |
| WRITE_OBSIDIAN | vault+path+content_hash | 2 |

- 指数退避：例如 2s、5s、15s；不可恢复错误不自动无限重试。
- job 状态：pending/running/succeeded/failed/cancelled。
- 每个 job 必须可通过 request_id / job_id 查询。
- 保存 adapter_version、compiler_version、prompt_version，保证问题可复现。

## 16. 测试与验收标准

### 16.1 Unit Test
- Normalizer：同一平台不同 DOM 结构可以得到相同 Schema。
- Hash：空格变化策略明确且测试覆盖。
- Markdown Writer：代码块、表格、LaTeX 不破坏。
- Dedup：同 message 不重复。
- Merge Planner：create/update/merge/ignore/review 全分支覆盖。

### 16.2 Adapter Fixture Test
每个平台至少保存：1 个最小对话、1 个多轮对话、1 个代码块对话、1 个表格/Markdown 对话、1 个长对话、1 个异常页面 fixture。禁止只依赖线上页面测试。

### 16.3 E2E 验收
| 编号 | 场景 | 通过标准 |
| --- | --- | --- |
| E2E-01 | 保存当前 DeepSeek 对话 | Raw Conversation/Message 入库，Markdown 可选写入。 |
| E2E-02 | 豆包历史批量导出 | 至少 20 条测试会话中 >=95% 成功。 |
| E2E-03 | 重复同步 | 第二次同步不生成重复 message。 |
| E2E-04 | Claude 编译 | 生成结构化 items，且 JSON 可校验。 |
| E2E-05 | 已有知识合并 | 识别重复并给出 merge/update，而非无脑创建新 note。 |
| E2E-06 | 冲突知识 | Verified 与新候选冲突时进入 review。 |
| E2E-07 | Obsidian写入 | frontmatter 完整，链接可追溯。 |
| E2E-08 | API失败 | Raw 数据仍存在，job 标记 retryable。 |
| E2E-09 | 页面结构变化 | Adapter health check 失败并给出明确错误，不产生错误数据。 |


### 16.4 性能基线
| 测试 | MVP目标 |
| --- | --- |
| SQLite 导入 10,000 messages | 在普通桌面环境可完成且不明显卡死 UI。 |
| FTS 查询 | P95 < 300ms（本地 10 万级 message）。 |
| 单会话打开 | P95 < 500ms，不含 Claude API。 |
| 批量同步 | 由队列处理，不阻塞 Side Panel 主线程。 |


## 17. 开发里程碑
| 阶段 | 目标 | 交付物 |
| --- | --- | --- |
| M0 | 工程骨架 | monorepo、CI、代码规范、CLAUDE.md、DB migration |
| M1 | Universal Schema | models + SQLite + import API + markdown raw writer |
| M2 | Provider adapters | DeepSeek、豆包、智谱、ChatGPT、Claude |
| M3 | Extension UI | Side Panel、选择、批量、同步状态 |
| M4 | Claude Compiler | extract/classify/link/merge/review |
| M5 | Obsidian Knowledge | knowledge writer、links、review flow |
| M6 | E2E + hardening | fixtures、回归、日志、安全、打包 |

开发策略：每完成一个阶段都必须让测试通过并产出可运行版本，不允许先堆积所有功能再一次性联调。

## 18. 风险与兼容性策略

### 18.1 最大风险：第三方网页 DOM 变化
- Adapter 与核心业务完全隔离。
- Selector 统一管理。
- 页面版本/结构特征检测。
- 失败应安全停止，不猜测字段。
- 每个平台建立回归 fixtures。

### 18.2 Claude API 变化
- Model ID 全部配置化。
- Prompt version 化。
- Schema version 化。
- AI provider 层抽象为接口，后续可接其他模型。

### 18.3 Obsidian Vault 风险
- 写文件前计算 content_hash。
- 若现有文件被人工修改，检测冲突，不覆盖。
- 写入前产生临时文件，成功后原子替换。
- 保留 compiler metadata，便于后续维护。

## 19. 给开发型 AI 的实施指令
以下内容可以直接作为开发 AI 的首轮 system/task 指令。
```text
你现在负责实现 AI Knowledge Compiler。
```
```text
不要先写营销文案或大而全架构。先阅读本规格，创建 monorepo，并执行 M0→M1→M2… 的增量开发。
```
```text
强制原则：
```
```text
1. 不改变 Universal Conversation Schema，除非同时更新版本和迁移。
```
```text
2. Raw 数据不可被 AI 编译器覆盖。
```
```text
3. 所有 Provider 必须实现统一 Adapter 接口。
```
```text
4. Claude 输出必须通过 JSON Schema 校验。
```
```text
5. Knowledge 必须有 source_message_ids 或等价来源。
```
```text
6. Verified 内容不能被低置信度 Candidate 静默覆盖。
```
```text
7. 所有外部 API 和 DOM 解析都要有错误边界与重试策略。
```
```text
8. 每完成一个阶段必须运行测试。
```
```text
9. 不要引入 Redis、PostgreSQL、向量数据库等非 MVP 必需依赖。
```
```text
10. 优先保证 Windows + Chrome + Obsidian 本地可运行。
```
```text
每个开发阶段输出：
```
```text
- 已完成文件
```
```text
- 数据库变更
```
```text
- API 变更
```
```text
- 测试结果
```
```text
- 尚未完成项
```
```text
- 下一阶段建议
```
```text
开始顺序：
```
```text
M0 工程骨架 → M1 数据层 → M2 Adapter → M3 Extension UI → M4 Claude Compiler → M5 Obsidian → M6 E2E。
```

## 20. 附录：示例 Schema 与模板

### 20.1 Settings 示例
```text
{
```
```text
"backend_url": "http://127.0.0.1:38127",
```
```text
"claude": {
```
```text
"enabled": true,
```
```text
"model": "<configured-model-id>",
```
```text
"api_key_ref": "system-keychain:anthropic",
```
```text
"max_context_tokens": 50000
```
```text
},
```
```text
"obsidian": {
```
```text
"vault_path": "<local-path>",
```
```text
"raw_folder": "01_Raw",
```
```text
"knowledge_folder": "03_Knowledge"
```
```text
},
```
```text
"compile": {
```
```text
"auto_compile": false,
```
```text
"auto_merge_verified": false,
```
```text
"require_review_for_conflicts": true
```
```text
}
```
```text
}
```

### 20.2 Knowledge Merge Diff 结果示例
```text
{
```
```text
"action": "review",
```
```text
"existing_knowledge_id": "k_001",
```
```text
"candidate_id": "c_018",
```
```text
"reason": "核心命题相同，但新来源增加了例外条件。",
```
```text
"proposed_markdown_patch": "...",
```
```text
"conflicts": [
```
```text
{
```
```text
"field": "assumption",
```
```text
"existing": "...",
```
```text
"new": "...",
```
```text
"severity": "medium"
```
```text
}
```
```text
]
```
```text
}
```

### 20.3 参考资料
Obsidian Web Clipper 官方文档：https://obsidian.md/help/web-clipper
Obsidian Web Clipper Templates：https://obsidian.md/help/web-clipper/templates
Anthropic Claude Platform Docs：https://docs.anthropic.com/
Anthropic Prompting Best Practices：https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/prompt-templates-and-variables
Chat2Note OSS：https://github.com/shiquda/chat2note
chat-migrator OSS：https://github.com/xscanzm/chat-migrator
说明：以上资料用于确认现有能力边界与实现参考；本项目并不依赖这些项目的内部实现。现有 Chat2Note 已支持 ChatGPT、Claude、DeepSeek、Gemini、Kimi、豆包、元宝、Grok 等导出到 Markdown/JSON/TXT 和 Obsidian；chat-migrator 已覆盖 Kimi、豆包、DeepSeek、智谱清言、千问等历史迁移场景。Obsidian 官方 Web Clipper 支持模板、变量、选择器和 Interpreter，但其定位仍是网页剪藏，因此本项目的知识编译、跨对话合并和来源图谱属于额外能力。
文档结束。
