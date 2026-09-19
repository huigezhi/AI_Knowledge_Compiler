/**
 * 自动保存与历史遍历测试。
 *
 * 覆盖两件用户真正会遇到的事：
 * 1. 会话内容变化后自动入库（不再需要手动点按钮）；
 * 2. 「没点开过的历史会话」能被自动逐个打开采集，且结束后回到原页面。
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Conversation, ConversationSummary } from "@akc/schema";

type Listener = (
  message: unknown,
  sender: unknown,
  sendResponse: (response: unknown) => void,
) => boolean | void;

const listeners: Listener[] = [];
const tabsQuery = vi.fn();
const tabsGet = vi.fn();
const tabsUpdate = vi.fn();
const tabsSendMessage = vi.fn();
const runtimeSendMessage = vi.fn();
const fetchMock = vi.fn();

vi.stubGlobal("chrome", {
  runtime: {
    onMessage: { addListener: (fn: Listener) => listeners.push(fn) },
    onInstalled: { addListener: () => undefined },
    onStartup: { addListener: () => undefined },
    getManifest: () => ({ version: "0.1.0" }),
    sendMessage: runtimeSendMessage,
    lastError: undefined,
  },
  tabs: {
    query: tabsQuery,
    get: tabsGet,
    update: tabsUpdate,
    sendMessage: tabsSendMessage,
    onUpdated: { addListener: () => undefined },
  },
  sidePanel: { open: vi.fn(), setPanelBehavior: vi.fn() },
  alarms: { onAlarm: { addListener: () => undefined }, create: vi.fn(), get: vi.fn(async () => undefined), clear: vi.fn() },
});
vi.stubGlobal("fetch", fetchMock);

await import("../index");

function dispatch(message: unknown, sender: unknown = {}): Promise<unknown> {
  const listener = listeners[0]!;
  return new Promise((resolve) => {
    const handled = listener(message, sender, resolve);
    if (handled === false) resolve({ ok: false, code: "IGNORED" });
  });
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function conversation(id: string, title: string): Conversation {
  return {
    id: `local_doubao_${id}`,
    provider: "doubao",
    provider_conversation_id: id,
    title,
    messages: [
      {
        id: `${id}_0`,
        provider_message_id: "m1",
        conversation_id: `local_doubao_${id}`,
        role: "user",
        content: [{ type: "text", text: "你好" }],
        sequence: 0,
        content_hash: "sha256:aaa",
      },
    ],
    content_hash: "sha256:conv",
    schema_version: "1.0.0",
    adapter_version: "0.2.0",
  } as unknown as Conversation;
}

function summary(id: string, title: string): ConversationSummary {
  return {
    provider_conversation_id: id,
    title,
    url: `https://www.doubao.com/chat/${id}`,
  };
}

/** 推进一次 crawl：后台的遍历是 fire-and-forget，这里等它自己跑完。 */
async function waitForCrawl(predicate: () => boolean, timeoutMs = 15000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("等待遍历结束超时");
}

describe("自动保存", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    runtimeSendMessage.mockReset();
    fetchMock.mockResolvedValue(
      jsonResponse({ conversation_id: "local_doubao_1", created: true, created_messages: 1, updated_messages: 0 }),
    );
  });

  it("收到页面变化快照后自动入库，无需用户点击", async () => {
    const response = (await dispatch({
      type: "AKC/AUTO_SAVE",
      conversation: conversation("1", "测试会话"),
    })) as { ok: boolean; autoSave?: { saved: boolean; title?: string } };

    expect(response.ok).toBe(true);
    expect(response.autoSave?.saved).toBe(true);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/conversations/import");
    expect(String(init.body)).toContain("测试会话");
  });

  it("后端失败时返回可提示的错误，而不是让消息通道挂掉", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: { code: "X", message: "boom", retryable: false } }, 400));
    const response = (await dispatch({
      type: "AKC/AUTO_SAVE",
      conversation: conversation("1", "测试会话"),
    })) as { ok: boolean; code: string };

    expect(response.ok).toBe(false);
    expect(response.code).toBe("AUTO_SAVE_FAILED");
  });
});

describe("历史会话自动遍历", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    tabsUpdate.mockReset();
    tabsSendMessage.mockReset();
    tabsGet.mockReset();
    tabsQuery.mockReset();
    runtimeSendMessage.mockReset();
    tabsQuery.mockResolvedValue([{ id: 7 }]);
    tabsGet.mockResolvedValue({ id: 7, url: "https://www.doubao.com/chat/origin" });
  });

  it("依次打开每个历史会话采集，结束后回到原来的页面", async () => {
    const items = [summary("101", "会话甲"), summary("102", "会话乙")];

    // 模拟「页面真的切过去了」：抓取结果跟随当前导航到的 URL
    let currentUrl = "https://www.doubao.com/chat/origin";
    tabsUpdate.mockImplementation((_tabId: number, info: { url: string }) => {
      currentUrl = info.url;
      return Promise.resolve(undefined);
    });
    tabsSendMessage.mockImplementation((_tabId: number, message: { type: string }) => {
      if (message.type === "AKC/LIST_CONVERSATIONS") return Promise.resolve({ ok: true, items });
      if (message.type === "AKC/FETCH_CURRENT") {
        const id = /\/chat\/(\d+)/.exec(currentUrl)?.[1] ?? "origin";
        return Promise.resolve({ ok: true, conversation: conversation(id, `会话${id}`) });
      }
      return Promise.resolve({ ok: false, code: "UNSUPPORTED" });
    });
    fetchMock.mockResolvedValue(
      jsonResponse({ conversation_id: "x", created: true, created_messages: 1, updated_messages: 0 }),
    );

    const start = (await dispatch({ type: "AKC/CRAWL_START", tabId: 7 })) as { ok: boolean };
    expect(start.ok).toBe(true);

    await waitForCrawl(() => {
      const status = runtimeSendMessage.mock.calls.at(-1)?.[0] as { progress?: { running?: boolean } } | undefined;
      return status?.progress?.running === false;
    });

    // 两个目标都导航过，且最后回到用户原来的页面
    const navigated = tabsUpdate.mock.calls.map((call) => (call[1] as { url: string }).url);
    expect(navigated).toContain("https://www.doubao.com/chat/101");
    expect(navigated.at(-1)).toBe("https://www.doubao.com/chat/origin");

    const last = runtimeSendMessage.mock.calls.at(-1)?.[0] as {
      progress: { ok: number; failed: number; total: number };
    };
    expect(last.progress.total).toBe(2);
    expect(last.progress.ok).toBe(2);
    expect(last.progress.failed).toBe(0);
    // 用例里每次导航要等 1 秒真实时间，超时放宽
  }, 30_000);

  it("跳过后端已存在的会话，不重复打开", async () => {
    const items = [summary("101", "会话甲")];
    tabsSendMessage.mockImplementation((_tabId: number, message: { type: string }) => {
      if (message.type === "AKC/LIST_CONVERSATIONS") return Promise.resolve({ ok: true, items });
      return Promise.resolve({ ok: false, code: "UNSUPPORTED" });
    });
    // 后端列表里已经有 101 → 应当被跳过
    fetchMock.mockResolvedValue(
      jsonResponse({ items: [{ id: "local_doubao_101", provider: "doubao", provider_conversation_id: "101", title: "会话甲" }], total: 1 }),
    );

    await dispatch({ type: "AKC/CRAWL_START", tabId: 7 });
    await waitForCrawl(() => {
      const status = runtimeSendMessage.mock.calls.at(-1)?.[0] as { progress?: { running?: boolean } } | undefined;
      return status?.progress?.running === false;
    });

    const last = runtimeSendMessage.mock.calls.at(-1)?.[0] as {
      progress: { total: number; skipped: number };
    };
    expect(last.progress.total).toBe(0);
    expect(last.progress.skipped).toBe(1);
    expect(tabsUpdate).not.toHaveBeenCalledWith(7, { url: expect.stringContaining("101") });
  }, 20_000);

  it("没有 url 的历史项无法导航，计入跳过而不是失败", async () => {
    const items = [{ provider_conversation_id: "201", title: "无链接会话" }];
    tabsSendMessage.mockResolvedValue({ ok: true, items });
    fetchMock.mockResolvedValue(jsonResponse({ items: [], total: 0 }));

    await dispatch({ type: "AKC/CRAWL_START", tabId: 7 });
    await waitForCrawl(() => {
      const status = runtimeSendMessage.mock.calls.at(-1)?.[0] as { progress?: { running?: boolean } } | undefined;
      return status?.progress?.running === false;
    });

    const last = runtimeSendMessage.mock.calls.at(-1)?.[0] as { progress: { total: number; skipped: number } };
    expect(last.progress.total).toBe(0);
    expect(last.progress.skipped).toBe(1);
  }, 20_000);
});
