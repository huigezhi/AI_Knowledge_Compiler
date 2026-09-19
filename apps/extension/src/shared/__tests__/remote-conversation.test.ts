// @vitest-environment jsdom
/**
 * 免跳转采集（AKC/FETCH_REMOTE 的解析半边）回归测试。
 *
 * 背景：历史同步不再导航标签页，而是内容脚本同源 fetch 会话页 HTML 后离线解析。
 * 这里验证：同一套 adapter（root 换成离线 DOM）解析结果与"页面真渲染出来"一致，
 * 以及客户端渲染（离线 HTML 无消息）时给出可识别的错误而不是静默吞掉。
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { parseConversationFromHtml } from "@/shared/remote-conversation";

const FIXTURE_DIR = resolve(process.cwd(), "tests", "fixtures");
const DOUBAO_URL = "https://www.doubao.com/chat/aaaaaaaaaa";

function fixture(name: string): string {
  return readFileSync(resolve(FIXTURE_DIR, name), "utf8");
}

describe("免跳转采集：离线 HTML 解析", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("离线解析 doubao 会话页，结果与页面渲染一致", async () => {
    const conversation = await parseConversationFromHtml(DOUBAO_URL, fixture("doubao-minimal.html"));
    expect(conversation.provider).toBe("doubao");
    expect(conversation.provider_conversation_id).toBe("aaaaaaaaaa");
    expect(conversation.messages.length).toBeGreaterThan(0);
    expect(conversation.messages[0]?.role).toBe("user");
  });

  it("离线 HTML 没有消息节点（客户端渲染平台）时报可识别错误", async () => {
    await expect(
      parseConversationFromHtml(DOUBAO_URL, "<html><head><title>豆包</title></head><body><div>骨架屏</div></body></html>"),
    ).rejects.toThrow(/客户端渲染|暂不支持/);
  });

  it("不支持的平台直接拒绝", async () => {
    await expect(
      parseConversationFromHtml("https://example.com/chat/1", "<html><body>x</body></html>"),
    ).rejects.toThrow(/不支持的平台/);
  });
});
