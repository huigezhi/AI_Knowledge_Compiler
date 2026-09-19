/**
 * DOM 解析工具。
 *
 * 强制原则（需求文档 §7.2 / §7.3）：
 * * selector 只出现在各 Provider 的常量表里，**禁止散落在业务代码**；
 * * 遇到代码块 / 表格 / 引用必须保留结构，**不得只取 innerText**；
 * * 解析失败要给出明确错误，不猜测字段。
 */

import type { ContentBlock, MessageRole } from "@akc/schema";

/** 每个 Provider 必须提供的选择器常量表。 */
export interface Selectors {
  /** 一轮对话（user + assistant）的外层容器 */
  turn: string;
  /** 单条消息容器；缺失时退化为 turn */
  message: string;
  /** 消息角色来源：属性名（如 data-role / data-message-author-role）或选择器 */
  roleAttr: string;
  /** 消息正文容器 */
  content: string;
  /** 会话标题 */
  title: string;
  /** 历史会话列表项（用于批量同步） */
  historyItem: string;
  /** 历史项标题 */
  historyTitle: string;
  /** 判断当前是否在会话详情页 */
  conversationRoot: string;
}

export function queryAll(root: ParentNode, selector: string): Element[] {
  return Array.from(root.querySelectorAll(selector));
}

export function queryFirst(root: ParentNode, selector: string): Element | null {
  return root.querySelector(selector);
}

/** 从属性或回退策略推断角色；无法判断时返回 ``unknown``（不猜测）。 */
export function inferRole(element: Element, roleAttr: string): MessageRole {
  const raw = element.getAttribute(roleAttr) ?? element.closest(`[${roleAttr}]`)?.getAttribute(roleAttr);
  const value = (raw ?? "").toLowerCase();
  if (["user", "assistant", "system", "tool"].includes(value)) return value as MessageRole;
  // 次级策略：常见 class 命名
  const className = `${element.className ?? ""}`.toLowerCase();
  if (className.includes("user") || className.includes("human")) return "user";
  if (className.includes("assistant") || className.includes("bot") || className.includes("model")) {
    return "assistant";
  }
  return "unknown";
}

/**
 * 把正文容器转换为 ContentBlock 列表，保留代码块、表格与图片结构。
 */
export function extractBlocks(container: Element): ContentBlock[] {
  const blocks: ContentBlock[] = [];
  // 预格式化（代码块）优先按块处理
  const preBlocks = queryAll(container, "pre");
  if (preBlocks.length > 0) {
    let cursor: Node | null = container.firstChild;
    const preSet = new Set(preBlocks);
    while (cursor) {
      if (cursor.nodeType === Node.ELEMENT_NODE && preSet.has(cursor as Element)) {
        const pre = cursor as Element;
        const code = pre.querySelector("code");
        const language = languageOf(code ?? pre);
        blocks.push({ type: "code", language, text: (code ?? pre).textContent?.trim() ?? "" });
      } else if (cursor.nodeType === Node.ELEMENT_NODE && (cursor as Element).tagName === "TABLE") {
        const md = tableToMarkdown(cursor as Element);
        if (md) blocks.push({ type: "text", text: md });
      } else {
        const text = normalizeWhitespace(cursor.textContent ?? "");
        if (text) blocks.push({ type: "text", text });
      }
      cursor = cursor.nextSibling;
    }
  } else {
    for (const child of Array.from(container.children)) {
      if (child.tagName === "TABLE") {
        const md = tableToMarkdown(child);
        if (md) blocks.push({ type: "text", text: md });
      } else if (child.tagName === "IMG") {
        const src = (child as HTMLImageElement).getAttribute("src") ?? "";
        if (src) blocks.push({ type: "image", source_url: src });
      } else {
        const text = normalizeWhitespace(child.textContent ?? "");
        if (text) blocks.push({ type: "text", text });
      }
    }
    if (blocks.length === 0) {
      const text = normalizeWhitespace(container.textContent ?? "");
      if (text) blocks.push({ type: "text", text });
    }
  }
  return blocks.length > 0 ? blocks : [{ type: "text", text: "" }];
}

function languageOf(element: Element): string | undefined {
  const className = `${element.className ?? ""}`;
  const match = /(?:language|lang|hljs)-([a-z0-9+#-]+)/i.exec(className);
  return match?.[1]?.toLowerCase();
}

/** 表格 → Markdown（保留结构，需求文档 §7.3） */
export function tableToMarkdown(table: Element): string {
  const rows = queryAll(table, "tr");
  if (rows.length === 0) return "";
  const lines: string[] = [];
  rows.forEach((row, index) => {
    const cells = queryAll(row, "th,td").map((cell) => normalizeWhitespace(cell.textContent ?? ""));
    if (cells.length === 0) return;
    lines.push(`| ${cells.join(" | ")} |`);
    if (index === 0) lines.push(`| ${cells.map(() => "---").join(" | ")} |`);
  });
  return lines.join("\n");
}

export function normalizeWhitespace(value: string): string {
  return value.replace(/\r\n?/g, "\n").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
}

/**
 * 页面结构签名：用于检测第三方 DOM 变化。
 * 只包含结构特征（命中数量 + 选择器是否命中），不含用户内容。
 */
export function domSignature(root: ParentNode, selectors: Selectors): string {
  const turns = queryAll(root, selectors.turn).length;
  const messages = queryAll(root, selectors.message).length;
  const hasTitle = queryFirst(root, selectors.title) !== null;
  const hasRoot = queryFirst(root, selectors.conversationRoot) !== null;
  return `turns:${turns}|messages:${messages}|title:${hasTitle ? 1 : 0}|root:${hasRoot ? 1 : 0}`;
}
