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
    onStartup: { addListener: () => undefined },
    getManifest: () => ({ version: "0.1.0" }),
  },
  tabs: { query: tabsQuery, sendMessage: tabsSendMessage, onUpdated: { addListener: () => undefined } },
  sidePanel: { open: sidePanelOpen, setPanelBehavior: vi.fn() },
  alarms: { onAlarm: { addListener: () => undefined }, create: vi.fn(), get: vi.fn(async () => undefined), clear: vi.fn() },
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
    // 扩展更新后旧页面失联是最常见的场景，要给出"刷新平台页面"的针对性提示
    expect(response.ok).toBe(false);
    expect(response.code).toBe("CONTENT_SCRIPT_STALE");
    expect(response.message).toContain("刷新");
  });

  it("非失联类通信错误保持通用提示", async () => {
    tabsSendMessage.mockRejectedValue(new TypeError("cannot read properties of undefined"));
    const response = (await dispatch({ type: "AKC/LIST_CONVERSATIONS" })) as {
      ok: boolean;
      code: string;
      message: string;
    };
    expect(response.code).toBe("CONTENT_SCRIPT_UNAVAILABLE");
    expect(response.message).toContain("刷新页面");
  });

  it("当前标签页不是平台页时，回退到最近使用的聊天平台标签页", async () => {
    // 活动标签页没有 url（非平台页），但存在另一个豆包标签页
    tabsQuery.mockImplementation((query: Record<string, unknown>) => {
      if (query.active) return Promise.resolve([{ id: 9, url: "https://example.com/docs" }]);
      return Promise.resolve([
        { id: 9, url: "https://example.com/docs" },
        { id: 42, url: "https://www.doubao.com/chat/1" },
      ]);
    });
    tabsSendMessage.mockResolvedValue({ ok: true, provider: "doubao", page: "conversation" });

    const response = (await dispatch({ type: "AKC/DETECT_PAGE" })) as { ok: boolean };
    expect(tabsSendMessage).toHaveBeenCalledWith(42, { type: "AKC/DETECT_PAGE" });
    expect(response.ok).toBe(true);
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
