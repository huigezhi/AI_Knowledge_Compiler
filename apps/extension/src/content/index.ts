/**
 * Content Script —— 在目标平台页面里执行 Adapter。
 *
 * 安全边界（需求文档 §6.1）：
 * * 只读页面已渲染 DOM，不绕过平台认证；
 * * 不读取与采集无关的 localStorage / cookie / 账号密钥；
 * * 不向页面注入任何第三方请求。
 */

import type { AdapterHealth, Conversation, ConversationSummary, ProviderAdapter } from "@akc/schema";
import { adapterForUrl } from "@/adapters/registry";
import { logger } from "@/shared/logger";
import { isMessage, type Message, type MessageResponse } from "@/shared/messaging";

function currentAdapter(): ProviderAdapter {
  const adapter = adapterForUrl(window.location.href);
  if (!adapter) {
    throw new Error(`AKC 暂不支持当前页面：${window.location.href}`);
  }
  return adapter;
}

function ok(payload: Record<string, unknown>): MessageResponse {
  return { ok: true, ...payload } as MessageResponse;
}

function fail(error: unknown): MessageResponse {
  const message = error instanceof Error ? error.message : String(error);
  logger.warn("content_script_error", { message });
  return {
    ok: false,
    code: "ADAPTER_PARSE_FAILED",
    message,
    retryable: false,
  } satisfies MessageResponse;
}

async function handle(message: Message): Promise<MessageResponse> {
  switch (message.type) {
    case "AKC/DETECT_PAGE": {
      const adapter = adapterForUrl(window.location.href);
      return ok({
        provider: adapter?.id ?? null,
        page: adapter ? adapter.detectPage() : "unknown",
      });
    }
    case "AKC/LIST_CONVERSATIONS": {
      const items: ConversationSummary[] = await currentAdapter().listConversations({
        limit: message.limit,
      });
      return ok({ items });
    }
    case "AKC/FETCH_CURRENT": {
      const conversation: Conversation = await currentAdapter().fetchCurrentConversation();
      return ok({ conversation });
    }
    case "AKC/HEALTH_CHECK": {
      const health: AdapterHealth = await currentAdapter().healthCheck();
      return ok({ health });
    }
    default:
      return { ok: false, code: "UNSUPPORTED_MESSAGE", message: "不支持的消息类型" };
  }
}

chrome.runtime.onMessage.addListener((raw, _sender, sendResponse) => {
  if (!isMessage(raw)) return false;
  void handle(raw).then(sendResponse, (error) => sendResponse(fail(error)));
  return true;
});

logger.debug("content_script_ready", { url: window.location.href });
