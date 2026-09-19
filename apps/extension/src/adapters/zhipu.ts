/** 智谱清言 Adapter。 */

import type { ProviderAdapter } from "@akc/schema";
import { createDomAdapter, type AdapterContext } from "./base";
import type { Selectors } from "./dom-utils";

export const ADAPTER_VERSION = "0.1.0";

export const SELECTORS: Selectors = {
  turn: ".chat-item",
  message: "[data-role]",
  roleAttr: "data-role",
  content: ".chat-content, .markdown-body, .akc-content",
  title: ".chat-title, title",
  historyItem: 'a[href*="/chat/"]',
  historyTitle: ".title, .akc-history-title",
  conversationRoot: "main, #app",
};

const ID_RE = /\/chat\/([A-Za-z0-9_-]{6,})/;

export function createZhipuAdapter(context?: AdapterContext): ProviderAdapter {
  return createDomAdapter(
    {
      id: "zhipu",
      displayName: "智谱清言",
      adapterVersion: ADAPTER_VERSION,
      origins: ["chatglm.cn", "bigmodel.cn"],
      selectors: SELECTORS,
      conversationIdFromUrl: (url) => ID_RE.exec(url)?.[1] ?? null,
      conversationIdFromHref: (href) => ID_RE.exec(href)?.[1] ?? null,
    },
    context,
  );
}
