/**
 * ChatGPT Adapter。
 *
 * ⚠️ 页面结构变化时的修复顺序：
 *   1. 更新 ``SELECTORS``；
 *   2. 更新 ``apps/extension/tests/fixtures/chatgpt-*.html``（用 ``npm run fixtures`` 重新生成）；
 *   3. 跑单测；**最后**再改业务代码。
 */

import type { ProviderAdapter } from "@akc/schema";
import { createDomAdapter, type AdapterContext } from "./base";
import type { Selectors } from "./dom-utils";

export const ADAPTER_VERSION = "0.1.0";

export const SELECTORS: Selectors = {
  turn: '[data-testid^="conversation-turn"]',
  message: "[data-message-author-role]",
  roleAttr: "data-message-author-role",
  content: ".markdown, .whitespace-pre-wrap, .akc-content",
  title: "title, h1",
  historyItem: 'nav a[href*="/c/"]',
  historyTitle: ".truncate, .akc-history-title",
  conversationRoot: "main",
};

const UUID_RE = /\/c\/([0-9a-f-]{8,})/i;

export function createChatGPTAdapter(context?: AdapterContext): ProviderAdapter {
  return createDomAdapter(
    {
      id: "chatgpt",
      displayName: "ChatGPT",
      adapterVersion: ADAPTER_VERSION,
      origins: ["chatgpt.com", "chat.openai.com"],
      selectors: SELECTORS,
      conversationIdFromUrl: (url) => UUID_RE.exec(url)?.[1] ?? null,
      conversationIdFromHref: (href) => UUID_RE.exec(href)?.[1] ?? null,
    },
    context,
  );
}
