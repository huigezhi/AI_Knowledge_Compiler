/**
 * DeepSeek Adapter。
 *
 * ⚠️ 选择器来自**线上登录态实测**（2026-09-19，Chrome 153）：
 *   node scripts/verify-live.mjs --provider deepseek --url https://chat.deepseek.com/a/chat/s/<id>
 *
 * 实测事实：
 * - 会话 URL：`https://chat.deepseek.com/a/chat/s/<uuid>`（原来按 `/chat/<id>` 匹配会漏，故单独处理）
 * - 消息容器：`div.ds-message`（用户与 AI 各一个）
 * - **没有 role 属性**，角色靠后代标记判定：
 *   · AI 消息内含 `.ds-assistant-message-main-content`
 *   · 用户消息内含 `.ds-collapsible-text`
 * - 正文：AI 用 `.ds-assistant-message-main-content`，用户用 `.ds-collapsible-text`
 * - 历史列表：`a[href*="/a/chat/s/"]`，标题即链接自身文本（操作按钮是纯图标，无文字）
 * - 部分 class 带构建 hash（`_63c77b1` / `c08e6e93`），**禁止用作选择器**
 *
 * ⚠️ 已知限制：消息区是**虚拟列表**（`div.ds-virtual-list-visible-items`），
 * 只有当前视口内的消息在 DOM 中；超长对话需先滚动加载才能完整采集。
 */

import type { ProviderAdapter } from "@akc/schema";
import { createDomAdapter, type AdapterContext } from "./base";
import type { Selectors } from "./dom-utils";

export const ADAPTER_VERSION = "0.2.0";

export const SELECTORS: Selectors = {
  turn: ["div.ds-message"],
  message: ["div.ds-message"],
  // DeepSeek 没有角色属性
  roleAttr: ["data-role", "data-message-author-role"],
  assistantIfContains: [".ds-assistant-message-main-content"],
  userIfContains: [".ds-collapsible-text"],
  content: [
    ".ds-assistant-message-main-content",
    ".ds-collapsible-text",
    ".ds-markdown",
    ".akc-content",
  ],
  // 标题靠 document.title（"你好 - DeepSeek"），displayName 后缀会被自动剥离
  title: ["title"],
  historyItem: ['a[href*="/a/chat/s/"]'],
  // historyTitle 省略：取历史项自身的首个文本节点
  conversationRoot: ["#root", '[class*="ds-virtual-list"]', "main"],
};

const ID_RE = /\/a\/chat\/s\/([A-Za-z0-9_-]{6,})/;

export function createDeepSeekAdapter(context?: AdapterContext): ProviderAdapter {
  return createDomAdapter(
    {
      id: "deepseek",
      displayName: "DeepSeek",
      adapterVersion: ADAPTER_VERSION,
      origins: ["chat.deepseek.com"],
      selectors: SELECTORS,
      conversationIdFromUrl: (url) => ID_RE.exec(url)?.[1] ?? null,
      conversationIdFromHref: (href) => ID_RE.exec(href)?.[1] ?? null,
    },
    context,
  );
}
