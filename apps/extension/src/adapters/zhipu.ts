/**
 * 智谱清言（ChatGLM）Adapter。
 *
 * ⚠️ 选择器来自**线上登录态实测**（2026-09-19，Chrome 153）：
 *   node scripts/verify-live.mjs --provider zhipu --url "https://chatglm.cn/main/alltoolsdetail?cid=<id>"
 *
 * 实测事实：
 * - 会话 URL：`https://chatglm.cn/main/alltoolsdetail?lang=zh&cid=<id>` ——
 *   会话 ID 在 **cid 查询参数**里（不是路径），所以必须按 query 解析
 * - 一轮对话 = `div.item.conversation-item`，其中：
 *   · 用户消息：`div.conversation.question`（含 `.user-name`、`.question-txt`）
 *   · AI 消息：`div.answer`（含 `.assistant-name`、`.answer-content-wrap`）
 * - 消息容器用一个**逗号选择器**同时匹配两者：`.conversation.question, div.answer`
 * - 正文：AI 取 `.answer-content-wrap`；用户取 `.question-txt`
 *   （不能取 `.question-text-style`，它同时包含「复制入框」按钮文字）
 * - 思考过程在 `.advance-thinking`（与答案同级），采集时剔除
 * - 标题：`div.chat-top-section p.conversation-name`（旁边有 measure-span 同文副本，取自身文本即可）
 * - 历史列表：`div.history-list div.history-item`，标题在 `.title`
 *   ⚠️ 历史行**没有会话 ID**（只有 cid 存在于 URL），批量同步需按标题匹配，见 sidepanel
 * - Vue 的 `data-v-*` 是构建期哈希，**禁止用作选择器**
 */

import type { ProviderAdapter } from "@akc/schema";
import { createDomAdapter, type AdapterContext } from "./base";
import type { Selectors } from "./dom-utils";

export const ADAPTER_VERSION = "0.2.0";

export const SELECTORS: Selectors = {
  turn: [".conversation.question, div.answer"],
  message: [".conversation.question, div.answer"],
  roleAttr: ["data-role"],
  assistantIfMatches: ["div.answer"],
  userIfMatches: [".conversation.question"],
  content: [".answer-content-wrap", ".question-txt", ".markdown-body", ".akc-content"],
  // 剔除思考过程（与答案同级，避免混进知识）
  excludeFromContent: [".advance-thinking", ".thinking-content"],
  title: ["div.chat-top-section p.conversation-name", "title"],
  historyItem: [".history-list .history-item", ".history-item"],
  historyTitle: [".title"],
  conversationRoot: ["#mainchat", ".content", "main"],
};

/** 会话 ID 在 query 参数 cid 上（不在路径里）。 */
const CID_RE = /[?&]cid=([A-Za-z0-9_-]{6,})/;

export function createZhipuAdapter(context?: AdapterContext): ProviderAdapter {
  return createDomAdapter(
    {
      id: "zhipu",
      displayName: "智谱清言",
      adapterVersion: ADAPTER_VERSION,
      origins: ["chatglm.cn", "bigmodel.cn"],
      selectors: SELECTORS,
      conversationIdFromUrl: (url) => CID_RE.exec(url)?.[1] ?? null,
      conversationIdFromHref: (href) => CID_RE.exec(href)?.[1] ?? null,
    },
    context,
  );
}
