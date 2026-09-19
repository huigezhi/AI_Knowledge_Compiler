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

## 6. 采集真实页面结构（无法复现时的关键手段）

适配器开发/修复最大的障碍是平台需要登录，开发者拿不到真实 DOM。
用 `apps/extension/scripts/dom-probe.js`：把它粘贴到目标页面 Console 运行，
输出**脱敏后的结构描述**（文本全部替换为 `{n字}` 占位符）：

- `currentSelectors`：AKC 当前配置的每个选择器命中数量（0 即失效的那个）
- `dataAttrs` / `classHits`：带 message/chat/role 语义的属性与类名统计
- `repeatedSiblingSignatures`：重复出现的兄弟容器签名 —— 消息列表的典型形态
- `messageSamples`：疑似消息容器的嵌套结构（保留标签与属性，不含文字）
- `counts`：元素总数 / iframe 数 / shadow DOM 宿主数（用来判断是否被隔离在子文档里）

> 诊断顺序：先看 `counts.iframes` 与 `counts.shadowHosts`（非 0 说明当前注入方式取不到内容），
> 再看 `currentSelectors` 中哪个为 0，最后用 `repeatedSiblingSignatures` 与
> `messageSamples` 确定新的 `SELECTORS`。

### 自动化探针（推荐，省去手动粘贴）

`scripts/probe-real-page.mjs` 用 Playwright 直接驱动浏览器执行同一份探针：

```bash
# A. 连接带调试端口启动的 Chrome（推荐：不复制任何登录数据，窗口用户可见）
#    用户双击 scripts/windows/start-chrome-debug.bat 一次即可
node scripts/probe-real-page.mjs --cdp http://127.0.0.1:9222 \
  --url https://www.doubao.com/chat/ --send "你好" --out report.json --screenshot

# B. 用 Chrome 登录数据的副本启动独立实例（要求 Chrome 已完全退出）
node scripts/probe-real-page.mjs --clone-profile --url https://www.doubao.com/chat/
```

依赖 `playwright-core`（路径可用 `AKC_PW` 覆盖；浏览器可用 `AKC_CHROME` 覆盖）。

**实测踩过的坑（务必记住）**：

| 现象 | 原因与解法 |
| --- | --- |
| 输入的文字没进输入框 | 富文本编辑器（tiptap / ProseMirror）只接受真实按键序列，用 `pressSequentially`，`fill()` 无效 |
| 「未找到可用输入框」 | SPA 首帧还没有输入框，必须先 `waitForSelector` 再操作，不能立刻 `count()` |
| Cookies 复制报 EBUSY | Chrome 运行中对 Cookies SQLite 加排他锁（连共享读都不允许），必须完全退出 Chrome |
| 发送后页面无变化 | 游客态通常不允许发消息（豆包已实测），必须有登录态才能逼出消息容器结构 |

## 7. 实测结构记录（逐步补充，勿凭猜测改选择器）

### 豆包 `www.doubao.com`（2026-09-19 **线上登录态实测**，Chrome 153）

探测方式：`node scripts/verify-live.mjs --provider doubao --url https://www.doubao.com/chat/<id>`
（把生产适配器打包注入真实页面执行，见 §8）。**adapter_version 已升至 0.2.0。**

| 目标 | 实测选择器 | 命中 |
| --- | --- | --- |
| 消息容器 / turn | `[data-message-id]` | 每条消息 1 个（user、assistant 各一） |
| **角色判定** | AI：祖先 `[data-reply-message="true"]`；用户：自身 `justify-end` | 各 1 |
| 正文 | `[data-container-type="block-v2"]` | 每条消息 1 个 |
| 会话标题 | `[data-conversation-active="true"] span[class*="whitespace-nowrap"]:not([aria-hidden="true"])` | 1 |
| 历史列表项 | `a[id^="conversation_"]`（内含 `[data-conversation-id]`） | 每个会话 1 个 |
| 历史项标题 | `[data-conversation-id] span[class*="whitespace-nowrap"]:not([aria-hidden="true"])` | 1 |
| 会话根 | `#root` / `[data-container-name="main"]` | 1 |

### DeepSeek `chat.deepseek.com`（2026-09-19 线上实测，adapter 0.2.0）

| 目标 | 实测选择器 |
| --- | --- |
| 会话 ID | **在路径里**：`/a/chat/s/<uuid>`（原来按 `/chat/<id>` 匹配会漏 → detectPage 失效） |
| 消息容器 | `div.ds-message` |
| 角色判定 | AI：**内含** `.ds-assistant-message-main-content`；用户：**内含** `.ds-collapsible-text` |
| 正文 | AI `.ds-assistant-message-main-content`；用户 `.ds-collapsible-text` |
| 历史列表 | `a[href*="/a/chat/s/"]`（标题即链接自身文本） |
| 标题 | 取自 `document.title`（"你好 - DeepSeek"，displayName 后缀自动剥离） |

⚠️ **虚拟列表**：消息区是 `div.ds-virtual-list-visible-items`，只有视口内的消息在 DOM 里，
超长对话需先滚动加载。class 带构建 hash（`_63c77b1`），禁止用作选择器。

### 智谱清言 `chatglm.cn`（2026-09-19 线上实测，adapter 0.2.0）

| 目标 | 实测选择器 |
| --- | --- |
| 会话 ID | **在查询参数里**：`?cid=<id>`（不在路径上） |
| 消息容器 | 逗号选择器 `.conversation.question, div.answer`（一问一答各一个元素） |
| 角色判定 | AI 自身匹配 `div.answer`；用户自身匹配 `.conversation.question` |
| 正文 | AI `.answer-content-wrap`；用户 `.question-txt`（**不能取 `.question-text-style`**，它含"复制入框"按钮文字） |
| 思考块 | `.advance-thinking`（与答案同级）→ 用 excludeFromContent 剔除 |
| 标题 | `div.chat-top-section p.conversation-name`（旁边有 measure-span 同文副本，取自身文本） |
| 历史列表 | `.history-list .history-item`，标题 `.title` |

⚠️ **历史行没有任何会话 ID**（只有 cid 在 URL 上）。因此 `listConversations` 会用
`title:<标题>` 作为占位 ID，批量同步按**标题**匹配（见 `sidepanel/main.ts#fetchConversationById`）。
Vue 的 `data-v-*` 是构建期哈希，禁止用作选择器。

### 三个平台共同的坑（都是线上撞出来的）

1. **不存在 `data-role`** —— 最初推断的 `[data-role]` / `.message-item` 在真实页面上命中 0，
   这是用户报「未匹配到任何消息节点」的直接原因。角色只能靠 `data-reply-message` + `justify-end`。
2. **class 名带构建 hash**（`content-jn3se3` / `nav-link-IkIer0`），随版本变化，**禁止作为选择器**。
3. **标题有 aria-hidden 的影子副本**：豆包为做行内省略会额外渲染一份 `aria-hidden="true"` +
   `visibility:hidden` 的重复文本。不排除它，标题会变成「标题标题」。
   因此标题选择器必须带 `:not([aria-hidden="true"])`，并且取值用 `readTitle`（优先元素自身文本节点）。

另外：`excludeFromContent` 会剔除 AI 回复里的「已完成思考」过程块
（`[data-plugin-identifier*="thinking_block"]`）—— 它是过程噪声，不该进知识库。

**仍然待办**：其余 4 个平台的选择器同样是推断的，应逐一用同一套流程校准。

## 8. 线上验证（改完适配器必须做这一步）

fixtures 单测只能证明"逻辑没退化"，证明不了"选择器在真实页面上有效"。真正的门禁是：

```bash
# 1) 用户侧：双击 scripts/windows/start-chrome-debug.bat 启动带调试端口的独立 Chrome，
#    并在该窗口里登录目标平台（登录态保存在 AKC-DebugProfile，一次即可）
# 2) 开发者侧：把生产适配器打包注入真实页面执行
node apps/extension/scripts/verify-live.mjs --provider doubao \
  --url https://www.doubao.com/chat/<conversation-id>
```

脚本会打印健康检查、标题、消息数、**角色序列**、内容块类型、历史标题，并以
`[verify] PASS / FAIL` 给出结论。它执行的是 `src/adapters/**` 的**同一份生产代码**
（esbuild 现场打包），不是另写的复刻逻辑。

> 为什么不用"打开新浏览器"的常规自动化：目标平台需要登录，而全新实例没有登录态；
> Chrome 136+ 又禁止在默认配置目录上开调试端口，因此必须使用独立配置目录。

## 9. 页面结构变化时的标准修复流程

0. 先跑上面 §6 的探针，拿到真实结构（不要盲改选择器）；
1. 更新 `src/adapters/<provider>.ts` 的 `SELECTORS`
   （支持候选列表，按优先级排列；候选必须精确，宁可失败也不产出脏数据）；
2. 更新 `scripts/gen-fixtures.mjs` 中对应平台的 DOM 结构；
3. `npm run fixtures` 重新生成 fixtures；
4. `npm run test`（fixture 测试应通过）；
5. 必要时同步 `apps/backend/akc/services/provider_registry.py` 的 `adapter_version`；
6. **最后**才改动业务代码。

`healthCheck()` 返回 `dom_version`（`turns:N|messages:N|title:0/1|root:0/1`），
Side Panel 会显示它；`degraded` / `unhealthy` 时给出明确提示而不是产出错误数据。
