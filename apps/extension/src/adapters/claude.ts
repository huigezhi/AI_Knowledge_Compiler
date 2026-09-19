/** Claude Adapter —— 处理长消息、代码块与附件（需求文档 §7.2）。 */

import type { ProviderAdapter } from "@akc/schema";
import { createDomAdapter, type AdapterContext } from "./base";
import type { Selectors } from "./dom-utils";

export const ADAPTER_VERSION = "0.1.0";

export const SELECTORS: Selectors = {
  turn: "[data-test-render-count]",
  message: "[data-message-author-role]",
  roleAttr: "data-message-author-role",
  content: ".font-claude-message, .grid, .akc-content",
  title: "title, h1",
  historyItem: 'a[href^="/chat/"]',
  historyTitle: ".truncate, .akc-history-title",
  conversationRoot: "main",
};

const ID_RE = /\/chat\/([A-Za-z0-9-]{6,})/;

export function createClaudeAdapter(context?: AdapterContext): ProviderAdapter {
  return createDomAdapter(
    {
      id: "claude",
      displayName: "Claude",
      adapterVersion: ADAPTER_VERSION,
      origins: ["claude.ai"],
      selectors: SELECTORS,
      conversationIdFromUrl: (url) => ID_RE.exec(url)?.[1] ?? null,
      conversationIdFromHref: (href) => ID_RE.exec(href)?.[1] ?? null,
    },
    context,
  );
}
