/**
 * Background Service Worker（MV3）。
 *
 * 职责边界：消息路由 + 浏览器能力调用（tab / side panel）+ **入库**。
 * 采集仍在 content script 的 adapter 里，编译与写入仍在本地后端；
 * 这里只负责把采集结果送到后端，以及编排历史会话的自动遍历。
 */

import type { Conversation, ConversationSummary } from "@akc/schema";
import { adapterForUrl } from "@/adapters/registry";
import { AkcApiClient } from "@/shared/api-client";
import { logger } from "@/shared/logger";
import { isMessage, type CrawlProgress, type Message, type MessageResponse } from "@/shared/messaging";
import { loadSettings, type ExtensionSettings } from "@/shared/settings";

chrome.runtime.onInstalled.addListener(() => {
  // 点击扩展图标直接打开 Side Panel（Chrome 116+）
  void chrome.sidePanel?.setPanelBehavior?.({ openPanelOnActionClick: true });
  logger.info("extension_installed", { version: chrome.runtime.getManifest().version });
});

function isPlatformTab(url: string | undefined): boolean {
  if (!url) return false;
  return adapterForUrl(url) !== null;
}

/**
 * 找到应该与侧边栏对话的标签页。
 *
 * 侧边栏是**窗口级**的：用户在豆包打开侧边栏后切到别的标签页查资料，
 * 侧边栏不能因此废掉。所以优先用当前活动标签页，不是平台页时
 * 回退到「最近用过的聊天平台标签页」，最后才用活动标签页兜底（让它报错）。
 */
async function resolvePlatformTabId(): Promise<number | undefined> {
  const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (active?.id !== undefined && isPlatformTab(active.url)) return active.id;

  const all = await chrome.tabs.query({});
  const platformTabs = all
    .filter((tab) => tab.id !== undefined && isPlatformTab(tab.url))
    .sort(
      (a, b) =>
        ((b as { lastAccessed?: number }).lastAccessed ?? 0) -
        ((a as { lastAccessed?: number }).lastAccessed ?? 0),
    );
  return platformTabs[0]?.id ?? active?.id;
}

async function toContentScript(tabId: number, message: Message): Promise<unknown> {
  return chrome.tabs.sendMessage(tabId, message);
}

async function clientFor(settings: ExtensionSettings): Promise<AkcApiClient> {
  return new AkcApiClient({
    backendUrl: settings.backendUrl,
    authToken: settings.authToken,
  });
}

// ------------------------------------------------------------------ 历史遍历
/**
 * 历史遍历状态。
 *
 * 为什么需要遍历：adapter 只能读**当前渲染出来的 DOM**，所以「没点开的会话」
 * 在页面里根本不存在。要采到它们，只能依次把页面切到每个会话再读 ——
 * 这正是这里做的事：导航 → 等渲染 → 采集 → 入库 → 下一个，结束后回到原页面。
 */
interface CrawlState {
  running: boolean;
  cancelRequested: boolean;
  tabId: number | null;
  originalUrl: string | null;
  progress: CrawlProgress;
}

const crawl: CrawlState = {
  running: false,
  cancelRequested: false,
  tabId: null,
  originalUrl: null,
  progress: {
    running: false,
    total: 0,
    done: 0,
    ok: 0,
    failed: 0,
    skipped: 0,
  },
};

/** 把进度推给侧边栏；侧边栏没打开时静默失败（不去污染控制台）。 */
function broadcastProgress(): void {
  try {
    chrome.runtime.sendMessage({ type: "AKC/CRAWL_PROGRESS", progress: crawl.progress }, () => {
      void chrome.runtime.lastError;
    });
  } catch {
    // 没有接收方，忽略
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 失败响应才有 `message`；成功分支取不到就用兜底文案。 */
function errorMessage(response: MessageResponse | null | undefined, fallback: string): string {
  if (response && "message" in response && response.message) return response.message;
  return fallback;
}

/** 历史项 ID 可能是 `title:<标题>` 占位（智谱清言列表里没有任何 ID）。 */
function isPlaceholderId(id: string): boolean {
  return id.startsWith("title:");
}

function matchesTarget(conversation: Conversation, target: ConversationSummary): boolean {
  if (isPlaceholderId(target.provider_conversation_id)) {
    const expected = target.provider_conversation_id.slice("title:".length);
    return conversation.title === expected;
  }
  return conversation.provider_conversation_id === target.provider_conversation_id;
}

/**
 * 导航到某个会话并等到页面真的渲染出它。
 *
 * 不依赖 load 事件：SPA 常常是客户端路由，status 根本不变。
 * 改为轮询「当前抓到的是不是目标会话」，既覆盖整页刷新也覆盖 SPA 跳转。
 */
async function navigateAndFetch(
  tabId: number,
  target: ConversationSummary,
  timeoutSeconds: number,
): Promise<Conversation> {
  const deadline = Date.now() + Math.max(5, timeoutSeconds) * 1000;
  await chrome.tabs.update(tabId, { url: target.url });

  let lastError = "";
  while (Date.now() < deadline) {
    if (crawl.cancelRequested) throw new Error("已取消");
    await sleep(1000);
    try {
      const response = (await toContentScript(tabId, { type: "AKC/FETCH_CURRENT" })) as MessageResponse;
      if (response?.ok && "conversation" in response) {
        const conversation = response.conversation;
        if (conversation.messages.length > 0 && matchesTarget(conversation, target)) {
          return conversation;
        }
        lastError = `页面仍显示「${conversation.title}」，等待目标会话渲染`;
      } else {
        lastError = errorMessage(response, "content script 未响应");
      }
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
  }
  throw new Error(lastError || "等待会话渲染超时");
}

async function runCrawl(tabId: number, limit: number, skipExisting: boolean | undefined): Promise<void> {
  // 整个函数必须从头到尾在 try 里：fire-and-forget 调用（void runCrawl）
  // 抛出的任何异常都会变成未处理拒绝，被 Chrome 计入扩展页的「错误」按钮
  try {
    const settings = await loadSettings();
    const useSkipExisting = skipExisting ?? settings.crawlSkipExisting;
    const api = await clientFor(settings);

    const tab = await chrome.tabs.get(tabId);
    crawl.originalUrl = tab.url ?? null;
    crawl.tabId = tabId;
    crawl.progress = {
      running: true,
      total: 0,
      done: 0,
      ok: 0,
      failed: 0,
      skipped: 0,
    };
    broadcastProgress();
    const listed = (await toContentScript(tabId, {
      type: "AKC/LIST_CONVERSATIONS",
      limit,
    })) as MessageResponse;
    if (!listed?.ok || !("items" in listed)) {
      throw new Error(errorMessage(listed, "读取历史列表失败"));
    }
    const items = listed.items as ConversationSummary[];

    // 后端已有哪些会话：用于跳过，避免每次都把全部历史重跑一遍
    const existingIds = new Set<string>();
    const existingTitles = new Set<string>();
    if (useSkipExisting) {
      try {
        const known = await api.listConversations({ limit: 1000 });
        for (const item of known.items) {
          if (item.provider_conversation_id) existingIds.add(item.provider_conversation_id);
          if (item.title) existingTitles.add(item.title);
        }
      } catch {
        // 查不到就全量跑，不影响正确性
      }
    }

    const targets: ConversationSummary[] = [];
    for (const item of items) {
      // 没有 url 就没法导航过去，只能跳过（这类条目仍需手动打开一次）
      if (!item.url) {
        crawl.progress.skipped += 1;
        continue;
      }
      if (useSkipExisting) {
        const seen = isPlaceholderId(item.provider_conversation_id)
          ? existingTitles.has(item.provider_conversation_id.slice("title:".length))
          : existingIds.has(item.provider_conversation_id);
        if (seen) {
          crawl.progress.skipped += 1;
          continue;
        }
      }
      targets.push(item);
    }

    crawl.progress.total = targets.length;
    broadcastProgress();

    for (const [index, target] of targets.entries()) {
      if (crawl.cancelRequested) break;
      crawl.progress.current = target.title;
      broadcastProgress();
      try {
        const conversation = await navigateAndFetch(
          tabId,
          target,
          settings.crawlItemTimeoutSeconds,
        );
        await api.importConversation(conversation, {
          write_raw_to_obsidian: settings.writeRawToObsidian,
          compile: settings.autoCompile,
        });
        crawl.progress.ok += 1;
      } catch (error) {
        crawl.progress.failed += 1;
        crawl.progress.lastError = error instanceof Error ? error.message : String(error);
        logger.warn("crawl_item_failed", { title: target.title, error: crawl.progress.lastError });
      }
      crawl.progress.done = index + 1;
      broadcastProgress();
    }
  } catch (error) {
    crawl.progress.lastError = error instanceof Error ? error.message : String(error);
    // 预期内的失败（页面失联/遍历失败）已在 UI 里给用户提示，
    // 用 error 级别会把 chrome://extensions 的「错误」按钮点红，误导为扩展崩溃
    logger.warn("crawl_failed", { error: crawl.progress.lastError });
  } finally {
    // 无论成功、失败还是取消，都把标签页还给使用者
    if (crawl.originalUrl) {
      try {
        await chrome.tabs.update(crawl.tabId!, { url: crawl.originalUrl });
      } catch {
        // 回不去就算了，用户在标签页里自己点回去即可
      }
    }
    crawl.running = false;
    crawl.progress.running = false;
    crawl.progress.finishedAt = Date.now();
    crawl.progress.cancelled = crawl.cancelRequested;
    crawl.progress.current = undefined;
    crawl.cancelRequested = false;
    broadcastProgress();
  }
}

// ------------------------------------------------------------------ 自动保存
async function handleAutoSave(
  conversation: Conversation,
  fromTabId: number | undefined,
): Promise<MessageResponse> {
  // 遍历过程中由遍历流程自己入库，避免同一次采集被写两遍
  if (crawl.running && fromTabId !== undefined && fromTabId === crawl.tabId) {
    return { ok: true, autoSave: { saved: false, reason: "crawl" } };
  }
  const settings = await loadSettings();
  const api = await clientFor(settings);
  try {
    await api.importConversation(conversation, {
      write_raw_to_obsidian: settings.writeRawToObsidian,
      compile: settings.autoCompile,
    });
    crawl.progress.lastAutoSaveAt = Date.now();
    crawl.progress.lastAutoSaveTitle = conversation.title;
    broadcastProgress();
    return { ok: true, autoSave: { saved: true, title: conversation.title } };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    logger.warn("auto_save_failed", { error: message });
    return { ok: false, code: "AUTO_SAVE_FAILED", message, retryable: true };
  }
}

// ------------------------------------------------------------------ 消息路由
chrome.runtime.onMessage.addListener((raw, sender, sendResponse) => {
  if (!isMessage(raw)) return false;
  const message = raw;

  void (async () => {
    try {
      // 侧边栏订阅的进度推送，只做展示，不产生响应
      if (message.type === "AKC/CRAWL_PROGRESS") return;

      if (message.type === "AKC/AUTO_SAVE") {
        sendResponse(await handleAutoSave(message.conversation, sender.tab?.id));
        return;
      }

      if (message.type === "AKC/CRAWL_START") {
        if (crawl.running) {
          sendResponse({ ok: false, code: "CRAWL_BUSY", message: "已有遍历任务在进行中" });
          return;
        }
        // 遍历要在平台标签页里导航，绝不能拿用户正在用的其它页面开刀
        const tabId = message.tabId ?? (await resolvePlatformTabId());
        if (!tabId) {
          sendResponse({
            ok: false,
            code: "NO_PLATFORM_TAB",
            message: "没有找到聊天平台标签页：请先打开豆包 / DeepSeek / ChatGPT 等页面再试。",
          });
          return;
        }
        crawl.running = true;
        sendResponse({ ok: true, crawl: crawl.progress });
        void runCrawl(tabId, message.limit ?? 200, message.skipExisting);
        return;
      }

      if (message.type === "AKC/CRAWL_CANCEL") {
        crawl.cancelRequested = true;
        sendResponse({ ok: true, crawl: crawl.progress });
        return;
      }

      if (message.type === "AKC/CRAWL_STATUS") {
        sendResponse({ ok: true, crawl: crawl.progress });
        return;
      }

      const tabId = "tabId" in message && message.tabId ? message.tabId : await resolvePlatformTabId();
      if (!tabId) {
        sendResponse({ ok: false, code: "NO_ACTIVE_TAB", message: "没有活动的标签页" } satisfies MessageResponse);
        return;
      }

      if (message.type === "AKC/OPEN_SIDE_PANEL") {
        await chrome.sidePanel?.open?.({ tabId });
        sendResponse({ ok: true } satisfies MessageResponse);
        return;
      }

      const result = (await toContentScript(tabId, message)) as MessageResponse;
      sendResponse(result ?? { ok: false, code: "NO_RESPONSE", message: "content script 未响应" });
    } catch (error) {
      const raw = error instanceof Error ? error.message : String(error);
      // 同上：这是已处理并提示用户的失败，warn 足够
      logger.warn("background_message_failed", { type: message.type, error: raw });
      // 扩展更新后旧页面里的 content script 会失联（"Receiving end does not exist"），
      // 这时的正确动作是刷新平台页面，而不是笼统的"通信失败"
      const stale = /receiving end|message port|frame with id/i.test(raw);
      sendResponse({
        ok: false,
        code: stale ? "CONTENT_SCRIPT_STALE" : "CONTENT_SCRIPT_UNAVAILABLE",
        message: stale
          ? "扩展刚更新过：请刷新（F5）聊天平台页面，然后重试。"
          : "无法与目标页面通信，请刷新页面后重试。",
      } satisfies MessageResponse);
    }
  })();

  return true; // 保持消息通道，等待异步响应
});

/** 内容脚本请求“打开侧边栏”的兜底路径。 */
chrome.runtime.onMessage.addListener((raw) => {
  if (isMessage(raw) && raw.type === "AKC/PING") {
    logger.debug("ping", { from: "content" });
  }
  return false;
});
