// @vitest-environment jsdom
/**
 * Adapter fixture 回归测试（需求文档 §16.2 / §18.1）。
 *
 * 每个平台 6 类 fixture：最小对话 / 多轮 / 代码块 / 表格 / 长对话 / 异常页面。
 * 页面结构变化时，这些测试会先失败，从而阻止错误数据进入知识库。
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import type { ProviderId } from "@akc/schema";
import { allAdapters, adapterById, adapterForUrl } from "../registry";
import { contentHash } from "@akc/schema/hash";

/**
 * fixtures 相对 **npm 包根目录**（apps/extension）解析：
 * jsdom 环境下 ``import.meta.url`` 不是 file: 协议，不能用 new URL(...) 读取文件。
 */
const FIXTURE_DIR = resolve(process.cwd(), "tests", "fixtures");
const URLS: Record<ProviderId, string> = {
  chatgpt: "https://chatgpt.com/c/aaaaaaaaaa",
  claude: "https://claude.ai/chat/aaaaaaaaaa",
  // DeepSeek 的会话 ID 在路径 /a/chat/s/<uuid>，不是 /chat/<id>
  deepseek: "https://chat.deepseek.com/a/chat/s/aaaaaaaaaa",
  doubao: "https://www.doubao.com/chat/aaaaaaaaaa",
  // 智谱清言的会话 ID 在查询参数 cid 上
  zhipu: "https://chatglm.cn/main/alltoolsdetail?lang=zh&cid=aaaaaaaaaa",
};

function loadFixture(provider: ProviderId, kind: string): void {
  const html = readFileSync(resolve(FIXTURE_DIR, `${provider}-${kind}.html`), "utf8");
  // jsdom 不允许跨源 replaceState，因此页面 URL 通过 AdapterContext 注入。
  document.documentElement.innerHTML = html;
}

/** 用 fixture URL 构造适配器实例（生产环境由 content script 注入当前页面）。 */
function adapterFor(provider: ProviderId) {
  return adapterById(provider, { url: URLS[provider], root: document })!;
}

const CASES = (Object.keys(URLS) as ProviderId[]).map((id) => ({ id, adapter: adapterFor(id) }));

describe("registry", () => {
  it("覆盖需求要求的 5 个平台", () => {
    expect(allAdapters().map((a) => a.id).sort()).toEqual([
      "chatgpt",
      "claude",
      "deepseek",
      "doubao",
      "zhipu",
    ]);
  });

  it("按 URL 匹配到正确适配器", () => {
    expect(adapterForUrl("https://chat.deepseek.com/chat/1")?.id).toBe("deepseek");
    expect(adapterForUrl("https://claude.ai/chat/1")?.id).toBe("claude");
    expect(adapterForUrl("https://www.doubao.com/chat/1")?.id).toBe("doubao");
    expect(adapterForUrl("https://chatglm.cn/chat/1")?.id).toBe("zhipu");
    expect(adapterForUrl("https://chatgpt.com/c/1")?.id).toBe("chatgpt");
    expect(adapterForUrl("https://example.com")).toBeNull();
  });
});

describe.each(CASES)("$id adapter", ({ id, adapter }) => {
  beforeEach(() => {
    document.documentElement.innerHTML = "";
  });

  it("解析最小对话", async () => {
    loadFixture(id, "minimal");
    const conversation = await adapter.fetchCurrentConversation();
    expect(conversation.provider).toBe(id);
    expect(conversation.title).toBe("SQL 性能优化");
    expect(conversation.messages).toHaveLength(2);
    expect(conversation.messages[0]?.role).toBe("user");
    expect(conversation.messages[1]?.role).toBe("assistant");
    expect(conversation.content_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
    for (const message of conversation.messages) {
      expect(message.content_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
    }
  });

  it("解析多轮对话并保持顺序", async () => {
    loadFixture(id, "multi");
    const conversation = await adapter.fetchCurrentConversation();
    expect(conversation.messages).toHaveLength(6);
    expect(conversation.messages.map((m) => m.sequence)).toEqual([0, 1, 2, 3, 4, 5]);
    // 标题必须干净（豆包会把标题嵌套渲染三层，取最外层会得到"标题标题标题"）
    expect(conversation.title).toBe("CTE 递归查询讨论");
    expect(conversation.messages[0]?.role).toBe("user");
    expect(conversation.messages[1]?.role).toBe("assistant");
  });

  it("保留代码块结构（不得只取 innerText）", async () => {
    loadFixture(id, "code");
    const conversation = await adapter.fetchCurrentConversation();
    const code = conversation.messages[1]?.content.find((block) => block.type === "code");
    expect(code).toBeDefined();
    expect(code?.type === "code" && code.language).toBe("sql");
    expect(code?.type === "code" && code.text).toContain("EXPLAIN ANALYZE");
  });

  it("保留表格结构", async () => {
    loadFixture(id, "table");
    const conversation = await adapter.fetchCurrentConversation();
    const text = conversation.messages
      .flatMap((m) => m.content.map((b) => (b.type === "text" || b.type === "code" ? b.text : "")))
      .join("\n");
    expect(text).toContain("| 方案 | 耗时 | 风险 |");
    expect(text).toContain("| --- | --- | --- |");
  });

  it("解析长对话（20 条）", async () => {
    loadFixture(id, "long");
    const conversation = await adapter.fetchCurrentConversation();
    expect(conversation.messages).toHaveLength(20);
  });

  it("不采集思考过程等噪声块（豆包「已完成思考」）", async () => {
    loadFixture(id, "minimal");
    const conversation = await adapter.fetchCurrentConversation();
    const all = conversation.messages
      .flatMap((m) => m.content.map((b) => (b.type === "text" || b.type === "code" ? b.text : "")))
      .join("\n");
    expect(all).not.toContain("已完成思考（这段是过程噪声，采集时应被剔除）");
    // fixture 里真实内容必须仍然存在
    expect(all).toContain("先看执行计划");
  });

  it("异常页面：抓取失败且健康检查不为 healthy", async () => {
    loadFixture(id, "error");
    await expect(adapter.fetchCurrentConversation()).rejects.toThrow();
    const health = await adapter.healthCheck();
    expect(health.status).not.toBe("healthy");
  });

  it("列出历史会话", async () => {
    loadFixture(id, "minimal");
    const items = await adapter.listConversations();
    expect(items).toHaveLength(3);
    expect(items[0]?.title).toBe("SQL 性能优化");
  });

  it("detectPage 能识别会话页", () => {
    loadFixture(id, "minimal");
    expect(adapter.detectPage()).toBe("conversation");
  });
});

describe("hash parity", () => {
  it("与后端 Python 实现保持逐字节一致", async () => {
    const sample = "  SQL  优化\r\n\r\n第二步：看执行计划  \n";
    expect(await contentHash(sample)).toBe(
      "sha256:5cb1e027b81484def6e977382db08ce80906026c7ddfaa508c342ebb7abde27b",
    );
  });
});

describe("adapterById", () => {
  it("未注册的平台返回 null", () => {
    expect(adapterById("gemini" as ProviderId)).toBeNull();
  });
});
