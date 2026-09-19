/**
 * 远程会话解析 —— 历史会话"免跳转"采集的核心。
 *
 * 以前采历史必须把标签页挨个导航到每个会话（用户眼看着页面跳来跳去）。
 * 现在：内容脚本与平台**同源**，直接 `fetch(会话URL, credentials=include)`
 * 拿到会话页 HTML，用 DOMParser 离线解析后交给同一套 Adapter——
 * 选择器逻辑零重复，平台改版也只改一处。
 *
 * 同源 fetch 自带登录态、不受 CORS 限制，也不需要任何额外 host 权限。
 */

import type { Conversation } from "@akc/schema";
import { adapterForUrl } from "@/adapters/registry";

export class RemoteFetchError extends Error {
  constructor(
    message: string,
    readonly code: string = "REMOTE_FETCH_FAILED",
  ) {
    super(message);
    this.name = "RemoteFetchError";
  }
}

/** 拉取会话页 HTML（同源、带登录态）。 */
export async function fetchConversationHtml(url: string): Promise<string> {
  let response: Response;
  try {
    response = await fetch(url, { credentials: "include", redirect: "follow" });
  } catch (error) {
    throw new RemoteFetchError(
      `会话页请求失败: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
  if (!response.ok) {
    throw new RemoteFetchError(`会话页返回 ${response.status}`, `REMOTE_HTTP_${response.status}`);
  }
  return response.text();
}

/**
 * 从会话页 HTML 解析出会话。
 *
 * 用与真实页面完全相同的 Adapter（只是把解析根换成离线 DOM）。
 * 平台若是纯客户端渲染，离线 HTML 里没有消息节点，这里会抛
 * ``AdapterParseError``——调用方按"该平台不支持免跳转采集"处理。
 */
export async function parseConversationFromHtml(url: string, html: string): Promise<Conversation> {
  const doc = new DOMParser().parseFromString(html, "text/html");
  // base：离线 DOM 里的相对链接/资源以会话 URL 为基准
  const base = doc.createElement("base");
  base.href = url;
  doc.head.appendChild(base);

  const adapter = adapterForUrl(url, { url, root: doc });
  if (!adapter) {
    throw new RemoteFetchError(`不支持的平台: ${url}`);
  }
  let conversation: Conversation;
  try {
    conversation = await adapter.fetchCurrentConversation();
  } catch (error) {
    // 离线 DOM 里没有任何消息节点时，adapter 会抛"未匹配到消息节点"——
    // 这通常意味着该平台是客户端渲染，离线 HTML 只是骨架屏
    const detail = error instanceof Error ? error.message : String(error);
    throw new RemoteFetchError(
      `会话页离线解析失败（该平台可能是客户端渲染，暂不支持免跳转采集）: ${detail}`,
      "REMOTE_EMPTY_RENDER",
    );
  }
  if (conversation.messages.length === 0) {
    throw new RemoteFetchError(
      "会话页为客户端渲染，离线 HTML 中没有消息内容（该平台暂不支持免跳转采集）",
      "REMOTE_EMPTY_RENDER",
    );
  }
  return conversation;
}

/** fetch + parse 一步到位。 */
export async function fetchRemoteConversation(url: string): Promise<Conversation> {
  return parseConversationFromHtml(url, await fetchConversationHtml(url));
}
