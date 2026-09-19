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
import { fetchRemoteConversation } from "@/shared/remote-conversation";
import { isMessage, type Message, type MessageResponse } from "@/shared/messaging";
import { loadSettings, resolveAutoSaveDelaySeconds } from "@/shared/settings";

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
    case "AKC/FETCH_REMOTE": {
      // 历史会话免跳转采集：同源抓取会话页 HTML 并离线解析，
      // 背景流程不需要真的把标签页导航过去（用户零感知）
      const conversation: Conversation = await fetchRemoteConversation(message.url);
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
const AUTO_SAVE_POLL_MS = 10_000;
/** 注入后先快速补采一次：用户常常是在会话早就打开着的时候才装上插件。 */
const FIRST_SNAPSHOT_MS = 1_500;

let lastSignature: string | null = null;
let debounceTimer: ReturnType<typeof setTimeout> | undefined;
let savingInFlight = false;
/** 最近一次成功抓取的会话：切换会话时用它先补存「上一个会话」。 */
let lastConversation: Conversation | null = null;
let lastUrl = typeof window === "undefined" ? "" : window.location.href;

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
    lastConversation = conversation;
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

/**
 * 切换会话前先把当前会话存下来。
 *
 * SPA 平台（豆包、智谱）点历史会话是客户端跳转：页面不刷新、content script 不重载，
 * 而 popstate 触发时 DOM 往往已经开始换内容了——那时再读已经读不到「上一个会话」。
 * 所以这里用**最近一次快照**补存（去抖窗口内刚更新过，通常就是最新内容），
 * 保证切走之前那一个会话不会丢。
 */
async function flushPendingConversation(reason: string): Promise<void> {
  const conversation = lastConversation;
  if (!conversation || savingInFlight) return;
  try {
    logger.debug("auto_save_flush", { reason, id: conversation.provider_conversation_id });
    await chrome.runtime.sendMessage({ type: "AKC/AUTO_SAVE", conversation });
  } catch {
    // 切换期间的补存失败不打扰用户：下一轮回到这个会话时还会再存
  }
}

/** SPA 里 URL 变了就算切换会话（不一定有 popstate）。 */
function watchConversationSwitch(delay: number): void {
  const check = (): void => {
    const url = window.location.href;
    if (url === lastUrl) return;
    lastUrl = url;
    // 先把旧会话存掉，再按新会话重新排一次采集
    void flushPendingConversation("switch");
    lastSignature = null;
    scheduleAutoSave(delay);
  };
  window.addEventListener("popstate", check);
  window.addEventListener("hashchange", check);
  setInterval(check, Math.min(AUTO_SAVE_POLL_MS, Math.max(2_000, delay * 1000)));
}

async function startAutoSave(): Promise<void> {
  const settings = await loadSettings();
  if (!settings.autoSave) return;
  const delay = resolveAutoSaveDelaySeconds(settings);

  // 打开会话页先存一次（哪怕你什么都不做，也会自动归档）。
  // 用比去抖更短的延迟做首次补采：插件装好后「早就开着」的会话也能立刻进库。
  setTimeout(() => void snapshot(), FIRST_SNAPSHOT_MS);
  scheduleAutoSave(delay);

  const observer = new MutationObserver(() => scheduleAutoSave(delay));
  observer.observe(document.body, { subtree: true, childList: true, characterData: true });

  // SPA 里切换会话不一定触发 popstate，兜底轮询 + 切换前补存
  setInterval(() => scheduleAutoSave(delay), AUTO_SAVE_POLL_MS);
  watchConversationSwitch(delay);
}

void startAutoSave();

logger.debug("content_script_ready", { url: window.location.href });
