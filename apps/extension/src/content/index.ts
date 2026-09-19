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
import { loadSettings } from "@/shared/settings";

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

// ------------------------------------------------------------------ 自动保存
/**
 * 自动保存：页面内容一变就重新排一次定时器，停手 `delay` 秒后才真正采集。
 *
 * 这样在连续对话（尤其是 AI 流式输出）期间不会被反复打断；
 * 采集本身是纯 DOM 读取，不修改页面、不发起任何第三方请求。
 */
const AUTO_SAVE_POLL_MS = 30_000;

let lastSignature: string | null = null;
let debounceTimer: ReturnType<typeof setTimeout> | undefined;
let savingInFlight = false;

function signatureOf(conversation: Conversation): string {
  const last = conversation.messages.at(-1);
  return [
    conversation.provider_conversation_id,
    conversation.messages.length,
    last?.content_hash ?? "",
  ].join("|");
}

async function snapshot(): Promise<void> {
  if (savingInFlight) return;
  savingInFlight = true;
  try {
    const adapter = adapterForUrl(window.location.href);
    if (!adapter || adapter.detectPage() !== "conversation") return;
    const conversation = await adapter.fetchCurrentConversation();
    // 空会话不入库：可能是刚点「新建对话」还没发消息
    if (conversation.messages.length === 0) return;
    const signature = signatureOf(conversation);
    if (signature === lastSignature) return;
    lastSignature = signature;
    logger.debug("auto_save_snapshot", {
      id: conversation.provider_conversation_id,
      messages: conversation.messages.length,
    });
    await chrome.runtime.sendMessage({ type: "AKC/AUTO_SAVE", conversation });
  } catch (error) {
    // 自动保存失败不应影响页面，也不该弹错：下一轮变化会再试
    logger.debug("auto_save_skipped", {
      message: error instanceof Error ? error.message : String(error),
    });
  } finally {
    savingInFlight = false;
  }
}

function scheduleAutoSave(delaySeconds: number): void {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => void snapshot(), Math.max(1, delaySeconds) * 1000);
}

async function startAutoSave(): Promise<void> {
  const settings = await loadSettings();
  if (!settings.autoSave) return;
  const delay = Math.max(1, settings.autoSaveDelaySeconds);

  // 打开会话页先存一次（哪怕你什么都不做，也会自动归档）
  scheduleAutoSave(delay);

  const observer = new MutationObserver(() => scheduleAutoSave(delay));
  observer.observe(document.body, { subtree: true, childList: true, characterData: true });

  // SPA 里切换会话不一定触发 popstate，兜底轮询
  setInterval(() => scheduleAutoSave(delay), AUTO_SAVE_POLL_MS);
  window.addEventListener("popstate", () => scheduleAutoSave(delay));
}

void startAutoSave();

logger.debug("content_script_ready", { url: window.location.href });
