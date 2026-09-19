# Provider Adapters

> **最大风险是第三方网页 DOM 变化。** 本文档定义适配器的边界、selector 管理纪律与回归策略。

## 1. 统一接口

```ts
interface ProviderAdapter {
  readonly id: string;
  readonly adapterVersion: string;
  matches(url: string): boolean;
  detectPage(): PageKind;                                  // conversation | history | unknown
  listConversations(options?: ListOptions): Promise<ConversationSummary[]>;
  fetchConversation(id: string): Promise<Conversation>;
  fetchCurrentConversation(): Promise<Conversation>;
  healthCheck(): Promise<AdapterHealth>;
}
```

所有平台共用 `createDomAdapter(def, context)` 工厂（`src/adapters/base.ts`），
各 Provider 只声明：

```ts
export const SELECTORS: Selectors = { turn, message, roleAttr, content, title, historyItem, historyTitle, conversationRoot };
```

**禁止**在 UI、background 或业务逻辑里出现任何 selector 字符串。

## 2. 运行上下文（可测试性）

```ts
createDeepSeekAdapter({ url: "https://chat.deepseek.com/chat/abc", root: document })
```

生产环境由 content script 传入当前页面；测试环境注入 fixture URL 与 jsdom document。
这样适配器不隐式依赖 `window.location`，单测可以覆盖全部解析分支。

## 3. 采集纪律（需求文档 §7.3）

| 规则 | 实现位置 |
| --- | --- |
| 只读已渲染 DOM，不绕过认证 | `base.ts` 全程 `querySelector` |
| 代码块保留结构与语言 | `dom-utils.ts#extractBlocks` |
| 表格转 Markdown 保留结构 | `dom-utils.ts#tableToMarkdown` |
| 图片/附件记录引用 | ContentBlock `image` / `file` |
| 虚拟列表：滚动 + 锚点 + hash 去重 | 由 `content_hash` 幂等保证；滚动加载属 P1 |
| 解析失败安全停止，不猜字段 | `AdapterParseError` |

## 4. 平台与选择器

| Provider | `origins` | `turn` | `message` | `roleAttr` |
| --- | --- | --- | --- | --- |
| ChatGPT | chatgpt.com, chat.openai.com | `[data-testid^="conversation-turn"]` | `[data-message-author-role]` | `data-message-author-role` |
| Claude | claude.ai | `[data-test-render-count]` | `[data-message-author-role]` | `data-message-author-role` |
| DeepSeek | chat.deepseek.com | `[data-testid='chat-turn']` | `[data-message-id]` | `data-role` |
| 豆包 | doubao.com | `[data-testid="message-item"]` | `[data-role]` | `data-role` |
| 智谱清言 | chatglm.cn, bigmodel.cn | `.chat-item` | `[data-role]` | `data-role` |

各文件的 `ADAPTER_VERSION` 必须与后端 `services/provider_registry.py` 记录一致。

## 5. Fixture 回归（需求文档 §16.2）

`npm run fixtures` 生成 `apps/extension/tests/fixtures/<provider>-<kind>.html`，
每个平台 6 类：

| kind | 覆盖点 |
| --- | --- |
| `minimal` | 最小单轮：角色识别、标题、哈希格式 |
| `multi` | 多轮顺序与 sequence 连续 |
| `code` | 代码块语言与内容保留 |
| `table` | 表格结构（表头分隔行） |
| `long` | 20 条消息的压力解析 |
| `error` | 结构异常：抓取应失败，健康检查不得为 healthy |

fixtures 已提交到仓库，**禁止只依赖线上页面测试**。

## 6. 页面结构变化时的标准修复流程

1. 更新 `src/adapters/<provider>.ts` 的 `SELECTORS`；
2. 更新 `scripts/gen-fixtures.mjs` 中对应平台的 DOM 结构；
3. `npm run fixtures` 重新生成 fixtures；
4. `npm run test`（fixture 测试应通过）；
5. 必要时同步 `apps/backend/akc/services/provider_registry.py` 的 `adapter_version`；
6. **最后**才改动业务代码。

`healthCheck()` 返回 `dom_version`（`turns:N|messages:N|title:0/1|root:0/1`），
Side Panel 会显示它；`degraded` / `unhealthy` 时给出明确提示而不是产出错误数据。
