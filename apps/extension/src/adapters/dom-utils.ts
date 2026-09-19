/**
 * DOM 解析工具。
 *
 * 强制原则（需求文档 §7.2 / §7.3）：
 * * selector 只出现在各 Provider 的常量表里，**禁止散落在业务代码**；
 * * 遇到代码块 / 表格 / 引用必须保留结构，**不得只取 innerText**；
 * * 解析失败要给出明确错误，不猜测字段。
 */

import type { ContentBlock, MessageRole } from "@akc/schema";

/**
 * 选择器规格：单个选择器，或**按优先级排列的候选列表**。
 *
 * 候选列表的作用是容纳平台的多套 DOM 变体（灰度、A/B、新旧版并存）：
 * 按顺序取第一个有命中的，全部落空才算解析失败。
 * 注意候选必须精确 —— 宁可失败也不能匹配到错误的元素产出脏数据。
 */
export type SelectorSpec = string | string[];

/** 每个 Provider 必须提供的选择器常量表。 */
export interface Selectors {
  /** 一轮对话（user + assistant）的外层容器 */
  turn: SelectorSpec;
  /** 单条消息容器；缺失时退化为 turn */
  message: SelectorSpec;
  /** 消息角色来源：属性名（可给多个候选，按顺序取第一个有效的） */
  roleAttr: SelectorSpec;
  /**
   * 角色标记（用于没有 role 属性的平台）：
   * - `assistantIfMatches` / `userIfMatches`：元素**自身或祖先**（≤3 层）命中即判定
   *   （豆包：[data-reply-message="true"] 在祖先上；justify-end 在自身）
   * - `assistantIfContains` / `userIfContains`：元素**自身或后代**命中即判定
   *   （DeepSeek：AI 消息内含 .ds-assistant-message-main-content，
   *    用户消息内含 .ds-collapsible-text）
   * 判定顺序：contains → matches → roleAttr → class 启发式 → unknown。
   */
  assistantIfMatches?: SelectorSpec;
  userIfMatches?: SelectorSpec;
  assistantIfContains?: SelectorSpec;
  userIfContains?: SelectorSpec;
  /** 消息正文容器 */
  content: SelectorSpec;
  /**
   * 从正文中剔除的子树（不影响页面，仅在采集副本上移除）。
   * 典型用途：豆包的「已完成思考」思考过程块 —— 它是过程的噪声，不是要沉淀的知识。
   */
  excludeFromContent?: SelectorSpec;
  /** 会话标题 */
  title: SelectorSpec;
  /** 历史会话列表项（用于批量同步） */
  historyItem: SelectorSpec;
  /** 历史项标题（可省略：省略时取历史项自身的文本） */
  historyTitle?: SelectorSpec;
  /** 判断当前是否在会话详情页 */
  conversationRoot: SelectorSpec;
}

export function queryAll(root: ParentNode, selector: SelectorSpec): Element[] {
  for (const candidate of Array.isArray(selector) ? selector : [selector]) {
    const found = Array.from(root.querySelectorAll(candidate));
    if (found.length > 0) return found;
  }
  return [];
}

export function queryFirst(root: ParentNode, selector: SelectorSpec): Element | null {
  for (const candidate of Array.isArray(selector) ? selector : [selector]) {
    const found = root.querySelector(candidate);
    if (found) return found;
  }
  return null;
}

/** 人类可读的选择器描述，用于错误信息与健康检查。 */
export function describeSelector(selector: SelectorSpec): string {
  return Array.isArray(selector) ? selector.join(" | ") : selector;
}

/**
 * 取**最深**的匹配节点（文档顺序中的最后一个）。
 *
 * 用途：有些平台为了做行内省略/渐变，把同一段文字放在多层嵌套元素里重复渲染
 * （豆包的会话标题就是三层嵌套），取最外层会得到 "标题标题标题"。
 * 嵌套场景下最内层节点在文档顺序里排在最后，因此取最后一个即为干净文本。
 */
export function queryDeepest(root: ParentNode, selector: SelectorSpec): Element | null {
  const matched = queryAll(root, selector);
  return matched.length > 0 ? (matched[matched.length - 1] as Element) : null;
}

/**
 * 取元素**自身**的首个非空文本节点。
 *
 * 用途：平台为做行内省略会给标题套多层元素，且每层都带一份相同文字
 * （豆包实测：外层 textContent 是「IP地址IP地址」）。此时整树 textContent 会重复，
 * 而元素自身的文本节点恰好是干净标题。
 * 元素没有直接文本节点（纯容器）时返回 null，由调用方回退。
 */
export function firstOwnText(element: Element | null): string | null {
  if (!element) return null;
  for (const node of Array.from(element.childNodes)) {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = (node.textContent ?? "").trim();
      if (text) return text;
    }
  }
  return null;
}

/** 标题类字段的统一取值：优先自身文本，其次整树文本。 */
export function readTitle(element: Element | null, fallback = ""): string {
  return (firstOwnText(element) ?? element?.textContent ?? fallback).trim();
}

/** 从属性或回退策略推断角色；无法判断时返回 ``unknown``（不猜测）。 */
const KNOWN_ROLES: ReadonlySet<string> = new Set(["user", "assistant", "system", "tool"]);

/** 角色标记：命中即判定（用于没有 role 属性的平台）。 */
export interface RoleMarkers {
  /** 元素自身或祖先命中 */
  assistant?: SelectorSpec;
  user?: SelectorSpec;
  /** 元素自身或后代命中 */
  assistantContains?: SelectorSpec;
  userContains?: SelectorSpec;
}

/** 元素自身或其后代是否命中任一选择器候选。 */
function matchesSelfOrDescendant(element: Element, spec: SelectorSpec | undefined): boolean {
  if (!spec) return false;
  for (const candidate of Array.isArray(spec) ? spec : [spec]) {
    try {
      if (element.matches(candidate) || element.querySelector(candidate) !== null) return true;
    } catch {
      // 非法选择器忽略
    }
  }
  return false;
}

/** 元素自身或前 N 层祖先是否命中任一选择器候选。 */
function matchesSelfOrAncestor(element: Element, spec: SelectorSpec | undefined, depth = 3): boolean {
  if (!spec) return false;
  const candidates = Array.isArray(spec) ? spec : [spec];
  let node: Element | null = element;
  for (let level = 0; node && level <= depth; level += 1) {
    for (const candidate of candidates) {
      try {
        if (node.matches(candidate)) return true;
      } catch {
        // 非法选择器忽略，不影响其它候选
      }
    }
    node = node.parentElement;
  }
  return false;
}

export function inferRole(
  element: Element,
  roleAttr: SelectorSpec,
  markers: RoleMarkers = {},
): MessageRole {
  // 1) 后代标记最具体（DeepSeek：AI 消息内含 .ds-assistant-message-main-content）
  if (matchesSelfOrDescendant(element, markers.assistantContains)) return "assistant";
  if (matchesSelfOrDescendant(element, markers.userContains)) return "user";

  // 2) 自身/祖先标记（豆包：data-reply-message 在祖先、justify-end 在自身）
  if (matchesSelfOrAncestor(element, markers.assistant)) return "assistant";
  if (matchesSelfOrAncestor(element, markers.user)) return "user";

  // 2) 显式角色属性
  for (const attr of Array.isArray(roleAttr) ? roleAttr : [roleAttr]) {
    const raw =
      element.getAttribute(attr) ?? element.closest(`[${attr}]`)?.getAttribute(attr) ?? undefined;
    const value = raw?.toLowerCase();
    if (value && KNOWN_ROLES.has(value)) return value as MessageRole;
    // 平台常用 "human"/"ai"/"bot" 之类的变体
    if (value === "human") return "user";
    if (value === "ai" || value === "bot" || value === "model" || value === "answer") return "assistant";
  }

  // 3) 次级策略：常见 class 命名
  const className = `${element.className ?? ""}`.toLowerCase();
  if (className.includes("user") || className.includes("human") || className.includes("question")) {
    return "user";
  }
  if (
    className.includes("assistant") ||
    className.includes("bot") ||
    className.includes("model") ||
    className.includes("answer") ||
    className.includes("reply")
  ) {
    return "assistant";
  }
  return "unknown";
}

/**
 * 把正文容器转换为 ContentBlock 列表，保留代码块、表格与图片结构。
 *
 * 实现要点：真实页面的正文常有多层包装（智谱是 `.answer-content-wrap > .markdown-body > p`），
 * 因此不能只看直接子节点；这里递归下钻，但**只在含有结构化元素时才继续下钻**，
 * 以免把「`<p>你好 <b>世界</b></p>`」这类段落拆成多个块。
 */
export function extractBlocks(container: Element): ContentBlock[] {
  const blocks: ContentBlock[] = [];

  const emitStructured = (el: Element): boolean => {
    const tag = el.tagName;
    if (tag === "PRE") {
      const code = el.querySelector("code");
      blocks.push({
        type: "code",
        language: languageOf(code ?? el),
        text: (code ?? el).textContent?.trim() ?? "",
      });
      return true;
    }
    if (tag === "TABLE") {
      const md = tableToMarkdown(el);
      if (md) blocks.push({ type: "text", text: md });
      return true;
    }
    if (tag === "IMG") {
      const src = el.getAttribute("src") ?? "";
      if (src) blocks.push({ type: "image", source_url: src });
      return true;
    }
    return false;
  };

  const walk = (node: Node): void => {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = normalizeWhitespace(node.textContent ?? "");
      if (text) blocks.push({ type: "text", text });
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const el = node as Element;
    if (emitStructured(el)) return;
    // 子树里还有结构化元素（pre/table/img）→ 继续下钻；否则整段作为文本块（保住行内格式不被打散）
    if (el.querySelector("pre, table, img") !== null) {
      for (const child of Array.from(el.childNodes)) walk(child);
      return;
    }
    const text = normalizeWhitespace(el.textContent ?? "");
    if (text) blocks.push({ type: "text", text });
  };

  for (const child of Array.from(container.childNodes)) walk(child);
  if (blocks.length === 0) {
    blocks.push({ type: "text", text: normalizeWhitespace(container.textContent ?? "") });
  }
  return blocks;
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
