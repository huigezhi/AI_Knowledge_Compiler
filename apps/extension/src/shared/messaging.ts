/**
 * 扩展内部消息协议（Side Panel ⇄ Background ⇄ Content Script）。
 *
 * 单一消息类型表 + 类型化 payload，避免各处散落字符串字面量。
 */

import type { AdapterHealth, Conversation, ConversationSummary, PageKind, ProviderId } from "@akc/schema";

/** 历史遍历的进度快照（后台持有，侧边栏轮询/订阅展示）。 */
export interface CrawlProgress {
  running: boolean;
  /** 本次计划采集的总数（已排除跳过项）。 */
  total: number;
  /** 已处理数（成功 + 失败）。 */
  done: number;
  ok: number;
  failed: number;
  /** 因后端已有而跳过的数量。 */
  skipped: number;
  /** 当前正在处理的会话标题。 */
  current?: string;
  /** 最近一条失败原因。 */
  lastError?: string;
  /** 最近一次自动保存的时间戳（毫秒）。 */
  lastAutoSaveAt?: number;
  /** 最近一次自动保存的会话标题。 */
  lastAutoSaveTitle?: string;
  finishedAt?: number;
  cancelled?: boolean;
}

export type Message =
  | { type: "AKC/PING" }
  | { type: "AKC/DETECT_PAGE"; tabId?: number }
  | { type: "AKC/LIST_CONVERSATIONS"; tabId?: number; limit?: number }
  | { type: "AKC/FETCH_CURRENT"; tabId?: number }
  | { type: "AKC/FETCH_REMOTE"; url: string; tabId?: number }
  | { type: "AKC/HEALTH_CHECK"; tabId?: number }
  | { type: "AKC/OPEN_SIDE_PANEL"; tabId?: number }
  // ---- 自动保存（content script 检测到变化后上报，由后台入库）----
  | { type: "AKC/AUTO_SAVE"; conversation: Conversation }
  // ---- 历史会话自动遍历 ----
  | { type: "AKC/CRAWL_START"; tabId?: number; limit?: number; skipExisting?: boolean }
  | { type: "AKC/CRAWL_CANCEL" }
  | { type: "AKC/CRAWL_STATUS" }
  /** 后台 → 侧边栏的进度推送（不经 chrome.runtime.onMessage 的响应通道）。 */
  | { type: "AKC/CRAWL_PROGRESS"; progress: CrawlProgress };

export type MessageResponse =
  | { ok: true; provider: ProviderId | null; page: PageKind }
  | { ok: true; items: ConversationSummary[] }
  | { ok: true; conversation: Conversation }
  | { ok: true; health: AdapterHealth }
  | { ok: true; crawl: CrawlProgress }
  | { ok: true; autoSave: { saved: boolean; reason?: string; title?: string } }
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
