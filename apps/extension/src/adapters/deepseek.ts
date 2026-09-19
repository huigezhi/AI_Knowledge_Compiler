/** DeepSeek Adapter —— DOM 变化与虚拟列表是主要风险（需求文档 §7.2）。 */

import type { ProviderAdapter } from "@akc/schema";
import { createDomAdapter, type AdapterContext } from "./base";
import type { Selectors } from "./dom-utils";

export const ADAPTER_VERSION = "0.1.0";

export const SELECTORS: Selectors = {
  turn: "[data-testid='chat-turn'], .ds-turn",
  message: "[data-message-id]",
  roleAttr: "data-role",
  content: ".ds-markdown, .md-content, .akc-content",
  title: ".chat-title, title",
  historyItem: 'a[href^="/chat/"]',
  historyTitle: ".title-text, .akc-history-title",
  conversationRoot: "main, #chat-container",
};

const ID_RE = /\/chat\/([A-Za-z0-9_-]{6,})/;

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
