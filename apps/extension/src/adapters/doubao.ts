/** 豆包 Adapter —— React 异步渲染 + 滚动加载，历史列表可能需要等待。 */

import type { ProviderAdapter } from "@akc/schema";
import { createDomAdapter, type AdapterContext } from "./base";
import type { Selectors } from "./dom-utils";

export const ADAPTER_VERSION = "0.1.0";

export const SELECTORS: Selectors = {
  turn: '[data-testid="message-item"], .message-item',
  message: "[data-role]",
  roleAttr: "data-role",
  content: ".message-content, .markdown-body, .akc-content",
  title: ".chat-title, title",
  historyItem: 'a[href*="/chat/"]',
  historyTitle: ".item-title, .akc-history-title",
  conversationRoot: "main, #root",
};

const ID_RE = /\/chat\/([A-Za-z0-9_-]{6,})/;

export function createDoubaoAdapter(context?: AdapterContext): ProviderAdapter {
  return createDomAdapter(
    {
      id: "doubao",
      displayName: "豆包",
      adapterVersion: ADAPTER_VERSION,
      origins: ["doubao.com"],
      selectors: SELECTORS,
      conversationIdFromUrl: (url) => ID_RE.exec(url)?.[1] ?? null,
      conversationIdFromHref: (href) => ID_RE.exec(href)?.[1] ?? null,
    },
    context,
  );
}
