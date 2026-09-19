/**
 * 扩展内部消息协议（Side Panel ⇄ Background ⇄ Content Script）。
 *
 * 单一消息类型表 + 类型化 payload，避免各处散落字符串字面量。
 */

import type { AdapterHealth, Conversation, ConversationSummary, PageKind, ProviderId } from "@akc/schema";

export type Message =
  | { type: "AKC/PING" }
  | { type: "AKC/DETECT_PAGE"; tabId?: number }
  | { type: "AKC/LIST_CONVERSATIONS"; tabId?: number; limit?: number }
  | { type: "AKC/FETCH_CURRENT"; tabId?: number }
  | { type: "AKC/HEALTH_CHECK"; tabId?: number }
  | { type: "AKC/OPEN_SIDE_PANEL"; tabId?: number };

export type MessageResponse =
  | { ok: true; provider: ProviderId | null; page: PageKind }
  | { ok: true; items: ConversationSummary[] }
  | { ok: true; conversation: Conversation }
  | { ok: true; health: AdapterHealth }
  | { ok: true }
  | { ok: false; code: string; message: string; retryable?: boolean };

/** content script 注入到页面后回传的探测结果 */
export interface PageDetection {
  provider: ProviderId | null;
  page: PageKind;
  url: string;
  title: string;
}

export function isMessage(value: unknown): value is Message {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { type?: unknown }).type === "string" &&
    (value as { type: string }).type.startsWith("AKC/")
  );
}
