/**
 * Background 消息路由测试。
 *
 * 覆盖：转发到 content script、缺少活动标签页、content script 不可达、打开侧边栏。
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

type Listener = (
  message: unknown,
  sender: unknown,
  sendResponse: (response: unknown) => void,
) => boolean | void;

const listeners: Listener[] = [];
const tabsQuery = vi.fn();
const tabsSendMessage = vi.fn();
const sidePanelOpen = vi.fn();

vi.stubGlobal("chrome", {
  runtime: {
    onMessage: { addListener: (fn: Listener) => listeners.push(fn) },
    onInstalled: { addListener: () => undefined },
    getManifest: () => ({ version: "0.1.0" }),
  },
  tabs: { query: tabsQuery, sendMessage: tabsSendMessage },
  sidePanel: { open: sidePanelOpen, setPanelBehavior: vi.fn() },
});

await import("../index");

/** 触发第一个 onMessage 监听器（background 中真正处理业务的那一个）。 */
function dispatch(message: unknown): Promise<unknown> {
  const listener = listeners[0]!;
  return new Promise((resolve) => {
    const handled = listener(message, {}, resolve);
    if (handled === false) resolve({ ok: false, code: "IGNORED" });
  });
}

describe("background message routing", () => {
  beforeEach(() => {
    tabsQuery.mockReset();
    tabsSendMessage.mockReset();
    sidePanelOpen.mockReset();
    tabsQuery.mockResolvedValue([{ id: 7 }]);
  });

  it("把采集请求转发给 content script 并回传结果", async () => {
    tabsSendMessage.mockResolvedValue({
      ok: true,
      provider: "deepseek",
      page: "conversation",
    });
    const response = (await dispatch({ type: "AKC/DETECT_PAGE" })) as {
      ok: boolean;
      provider: string;
    };
    expect(tabsSendMessage).toHaveBeenCalledWith(7, { type: "AKC/DETECT_PAGE" });
    expect(response.ok).toBe(true);
    expect(response.provider).toBe("deepseek");
  });

  it("没有活动标签页时返回明确错误", async () => {
    tabsQuery.mockResolvedValue([]);
    const response = (await dispatch({ type: "AKC/FETCH_CURRENT" })) as {
      ok: boolean;
      code: string;
    };
    expect(response.ok).toBe(false);
    expect(response.code).toBe("NO_ACTIVE_TAB");
  });

  it("content script 不可达时返回可提示用户的错误", async () => {
    tabsSendMessage.mockRejectedValue(new Error("Receiving end does not exist"));
    const response = (await dispatch({ type: "AKC/LIST_CONVERSATIONS" })) as {
      ok: boolean;
      code: string;
      message: string;
    };
    expect(response.ok).toBe(false);
    expect(response.code).toBe("CONTENT_SCRIPT_UNAVAILABLE");
    expect(response.message).toContain("刷新页面");
  });

  it("支持打开侧边栏", async () => {
    const response = (await dispatch({ type: "AKC/OPEN_SIDE_PANEL" })) as { ok: boolean };
    expect(sidePanelOpen).toHaveBeenCalledWith({ tabId: 7 });
    expect(response.ok).toBe(true);
  });

  it("忽略非 AKC 消息", async () => {
    const response = (await dispatch({ type: "OTHER/MESSAGE" })) as { code: string };
    expect(response.code).toBe("IGNORED");
  });
});
