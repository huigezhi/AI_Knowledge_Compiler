/**
 * 豆包 Adapter。
 *
 * ⚠️ 选择器全部来自**线上实测**（2026-09-19，Chrome 153 + 已登录账号），
 * 不是推断 —— 之前推断的 `[data-role]` / `.message-item` 在真实页面上根本不存在。
 *
 * 实测事实（详见 docs/adapters.md §7）：
 * - 单条消息容器：`[data-message-id]`（用户与 AI 各一个）
 * - **没有 role 属性**，角色靠两个稳定标记判断：
 *   · AI 消息的父容器带 `[data-reply-message="true"]`
 *   · 用户消息容器自身带 `justify-end`（右对齐）
 * - 正文容器：`[data-container-type="block-v2"]`
 * - class 名带构建 hash（`content-jn3se3`），**禁止用作选择器**
 * - 历史列表项：`a[id^="conversation_"]`，标题在其内 `span[class*="whitespace-nowrap"]`
 *
 * 页面结构变化时的修复顺序见 docs/adapters.md §8。
 */

import type { ProviderAdapter } from "@akc/schema";
import { createDomAdapter, type AdapterContext } from "./base";
import type { Selectors } from "./dom-utils";

export const ADAPTER_VERSION = "0.2.0";

export const SELECTORS: Selectors = {
  // 一条 user/assistant 消息即一个 turn
  turn: ["[data-message-id]"],
  message: ["[data-message-id]"],
  // 豆包没有角色属性，保留候选以防将来新增
  roleAttr: ["data-role", "data-author-role"],
  assistantIfMatches: ['[data-reply-message="true"]'],
  userIfMatches: [".justify-end"],
  content: ['[data-container-type="block-v2"]', ".message-content", ".markdown-body", ".akc-content"],
  // 剔除「已完成思考」的思考过程块：它是过程噪声，不是要沉淀的知识
  excludeFromContent: [
    '[data-plugin-identifier*="thinking_block"]',
    '[data-message-selection-module="thinking_progress"]',
  ],
  // 标题：豆包为做省略/跑马灯会渲染一个 aria-hidden 的影子副本（文本重复两遍），
  // 必须排除它，否则标题会变成「标题标题」。
  title: [
    '[data-conversation-active="true"] span[class*="whitespace-nowrap"]:not([aria-hidden="true"])',
    "title",
  ],
  historyItem: ['a[id^="conversation_"]', '[class*="conversation-item"]'],
  historyTitle: [
    '[data-conversation-id] span[class*="whitespace-nowrap"]:not([aria-hidden="true"])',
    '[data-conversation-id] span',
  ],
  conversationRoot: ["#root", '[data-container-name="main"]', "main"],
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
