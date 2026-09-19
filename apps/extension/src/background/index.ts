/**
 * Background Service Worker（MV3）。
 *
 * 职责边界：只做消息路由与浏览器能力调用（tab / side panel），
 * **不承载任何采集与业务逻辑**——采集在 content script 的 adapter 里，
 * 编译与写入在本地后端。
 */

import { logger } from "@/shared/logger";
import { isMessage, type Message, type MessageResponse } from "@/shared/messaging";

chrome.runtime.onInstalled.addListener(() => {
  // 点击扩展图标直接打开 Side Panel（Chrome 116+）
  void chrome.sidePanel?.setPanelBehavior?.({ openPanelOnActionClick: true });
  logger.info("extension_installed", { version: chrome.runtime.getManifest().version });
});

async function activeTabId(): Promise<number | undefined> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab?.id;
}

async function toContentScript(tabId: number, message: Message): Promise<unknown> {
  return chrome.tabs.sendMessage(tabId, message);
}

chrome.runtime.onMessage.addListener((raw, sender, sendResponse) => {
  if (!isMessage(raw)) return false;
  const message = raw;

  void (async () => {
    try {
      const tabId = "tabId" in message && message.tabId ? message.tabId : await activeTabId();
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
      logger.error("background_message_failed", {
        type: message.type,
        error: error instanceof Error ? error.message : String(error),
      });
      sendResponse({
        ok: false,
        code: "CONTENT_SCRIPT_UNAVAILABLE",
        message: "无法与目标页面通信，请刷新页面后重试。",
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
