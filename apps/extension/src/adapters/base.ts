/**
 * Provider Adapter 工厂。
 *
 * 所有平台共用的 DOM 采集逻辑集中在这里；各 Provider 只声明
 * 「选择器常量表 + 来源判定规则」，避免 selector 散落、便于页面结构变化时单点修复。
 */

import type {
  AdapterHealth,
  Conversation,
  ConversationSummary,
  Message,
  PageKind,
  ProviderAdapter,
  ProviderId,
} from "@akc/schema";
import { contentHash } from "@akc/schema/hash";
import type { Selectors } from "./dom-utils";
import {
  describeSelector,
  domSignature,
  extractBlocks,
  inferRole,
  queryAll,
  queryFirst,
} from "./dom-utils";

export class AdapterParseError extends Error {
  constructor(
    message: string,
    readonly provider: ProviderId,
    readonly retryable = false,
  ) {
    super(message);
    this.name = "AdapterParseError";
  }
}

export interface AdapterDefinition {
  id: ProviderId;
  displayName: string;
  adapterVersion: string;
  origins: string[];
  selectors: Selectors;
  /** 从 URL 提取 provider_conversation_id；无法提取返回 null。 */
  conversationIdFromUrl(url: string): string | null;
  /** 历史项 href → provider_conversation_id */
  conversationIdFromHref(href: string): string | null;
}

/** 运行上下文：生产环境由 content script 注入当前页面，测试环境注入 fixture。 */
export interface AdapterContext {
  /** 当前页面 URL；缺省取 ``window.location.href``。 */
  url?: string;
  /** 解析根节点；缺省取 ``document``。 */
  root?: ParentNode;
}

/** 统一实现：DOM 优先，不绕过平台认证，不读取与采集无关的 localStorage/cookie。 */
export function createDomAdapter(
  def: AdapterDefinition,
  context: AdapterContext = {},
): ProviderAdapter {
  const { selectors } = def;

  function root(): ParentNode {
    return context.root ?? document;
  }

  function pageUrl(): string {
    return context.url ?? (typeof window === "undefined" ? "" : window.location.href);
  }

  function detectPage(): PageKind {
    if (def.conversationIdFromUrl(pageUrl())) return "conversation";
    if (queryAll(root(), selectors.historyItem).length > 0) return "history";
    return "unknown";
  }

  function parseMessages(externalId: string, conversationId: string): Message[] {
    const messageNodes = queryAll(root(), selectors.message);
    const nodes = messageNodes.length > 0 ? messageNodes : queryAll(root(), selectors.turn);
    if (nodes.length === 0) {
      throw new AdapterParseError(
        `${def.displayName}: 未匹配到任何消息节点（selector: ${describeSelector(selectors.message)}）`,
        def.id,
      );
    }
    return nodes.map((node, index) => {
      const nodeId =
        node.getAttribute("data-message-id") ??
        node.getAttribute("id") ??
        `${externalId}:${index}`;
      const contentNode = queryFirst(node, selectors.content) ?? node;
      return {
        id: `${externalId}_${index}`,
        provider_message_id: nodeId,
        conversation_id: conversationId,
        role: inferRole(node, selectors.roleAttr),
        content: extractBlocks(contentNode),
        sequence: index,
        created_at: node.querySelector("time")?.getAttribute("datetime") ?? undefined,
        content_hash: "", // 由 buildConversation 统一计算
      };
    });
  }

  async function buildConversation(externalId: string): Promise<Conversation> {
    const titleNode = queryFirst(root(), selectors.title);
    const title = (titleNode?.textContent ?? document.title ?? "").trim() || "(untitled)";
    const conversationId = `local_${def.id}_${externalId}`;

    const messages: Message[] = [];
    for (const [index, raw] of parseMessages(externalId, conversationId).entries()) {
      messages.push({
        ...raw,
        sequence: index,
        content_hash: await contentHash(raw.content.map((block) => textOf(block)).join("\n")),
      });
    }

    const conv: Conversation = {
      id: conversationId,
      provider: def.id,
      provider_conversation_id: externalId,
      title,
      url: pageUrl(),
      messages,
      content_hash: "",
      schema_version: "1.0.0",
      adapter_version: def.adapterVersion,
    };
    conv.content_hash = await contentHash(
      messages.map((m) => `${m.role}:${m.content_hash}`).join("\n"),
    );
    return conv;
  }

  function currentExternalId(): string {
    const externalId = def.conversationIdFromUrl(pageUrl());
    if (!externalId) {
      throw new AdapterParseError(
        `${def.displayName}: 当前页面不是会话详情页（${pageUrl()}）`,
        def.id,
      );
    }
    return externalId;
  }

  return {
    id: def.id,
    adapterVersion: def.adapterVersion,

    matches(url: string): boolean {
      try {
        const host = new URL(url).hostname.toLowerCase();
        return def.origins.some((origin) => host === origin || host.endsWith(`.${origin}`));
      } catch {
        return false;
      }
    },

    detectPage,

    async listConversations(options): Promise<ConversationSummary[]> {
      const items = queryAll(root(), selectors.historyItem);
      const origin = new URL(pageUrl() || "https://example.com").origin;
      const summaries = items.map((item) => {
        const href = item.getAttribute("href") ?? "";
        const titleNode = queryFirst(item, selectors.historyTitle) ?? item;
        return {
          provider_conversation_id: def.conversationIdFromHref(href) ?? href,
          title: (titleNode.textContent ?? "").trim() || "(untitled)",
          url: href ? new URL(href, origin).toString() : undefined,
        };
      });
      const limit = options?.limit ?? 200;
      return summaries
        .filter((item) => Boolean(item.provider_conversation_id))
        .slice(0, limit);
    },

    async fetchCurrentConversation(): Promise<Conversation> {
      return buildConversation(currentExternalId());
    },

    async fetchConversation(id: string): Promise<Conversation> {
      const current = def.conversationIdFromUrl(pageUrl());
      if (current !== id) {
        throw new AdapterParseError(
          `${def.displayName}: 需要打开会话 ${id} 才能抓取（当前页面为 ${current ?? "非会话页"}）`,
          def.id,
        );
      }
      return buildConversation(id);
    },

    async healthCheck(): Promise<AdapterHealth> {
      const checkedAt = new Date().toISOString();
      const signature = domSignature(root(), selectors);
      const turns = queryAll(root(), selectors.turn).length;
      try {
        if (detectPage() === "unknown") {
          return {
            provider: def.id,
            status: "degraded",
            dom_version: signature,
            message: "未识别到会话页或历史列表，页面结构可能已变化",
            checked_at: checkedAt,
          };
        }
        if (detectPage() === "conversation" && turns === 0) {
          return {
            provider: def.id,
            status: "unhealthy",
            dom_version: signature,
            message: `未匹配到消息节点（selector: ${describeSelector(selectors.turn)}），请更新适配器与 fixtures`,
            checked_at: checkedAt,
          };
        }
        return {
          provider: def.id,
          status: "healthy",
          dom_version: signature,
          message: `已识别 ${turns} 轮对话`,
          checked_at: checkedAt,
        };
      } catch (error) {
        return {
          provider: def.id,
          status: "unhealthy",
          dom_version: signature,
          message: error instanceof Error ? error.message : String(error),
          checked_at: checkedAt,
        };
      }
    },
  };
}

function textOf(block: { type: string; text?: string }): string {
  return block.type === "code" ? `\`\`\`\n${block.text ?? ""}\n\`\`\`` : (block.text ?? "");
}
