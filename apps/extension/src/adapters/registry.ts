/**
 * Adapter 注册表：按 URL 选择适配器。
 *
 * 注册表是 Provider 与业务代码之间**唯一**的接触面，
 * UI 与后台脚本不得直接引用某个具体适配器。
 */

import type { ProviderAdapter, ProviderId } from "@akc/schema";
import { createChatGPTAdapter } from "./chatgpt";
import { createClaudeAdapter } from "./claude";
import { createDeepSeekAdapter } from "./deepseek";
import { createDoubaoAdapter } from "./doubao";
import { createZhipuAdapter } from "./zhipu";

import type { AdapterContext } from "./base";

type Factory = (context?: AdapterContext) => ProviderAdapter;

const FACTORIES: Factory[] = [
  createChatGPTAdapter,
  createClaudeAdapter,
  createDeepSeekAdapter,
  createDoubaoAdapter,
  createZhipuAdapter,
];

let cache: ProviderAdapter[] | null = null;

/**
 * 全部适配器实例。
 *
 * 不传 ``context`` 时使用真实 ``document`` / ``window.location``（生产路径，结果缓存）；
 * 传入 ``context`` 时（测试路径）每次新建实例，不污染缓存。
 */
export function allAdapters(context?: AdapterContext): ProviderAdapter[] {
  if (context) return FACTORIES.map((factory) => factory(context));
  cache ??= FACTORIES.map((factory) => factory());
  return cache;
}

/** 按 URL 匹配唯一适配器；无匹配返回 null（调用方负责提示“不支持的平台”）。 */
export function adapterForUrl(url: string, context?: AdapterContext): ProviderAdapter | null {
  return allAdapters(context).find((adapter) => adapter.matches(url)) ?? null;
}

export function adapterById(id: ProviderId, context?: AdapterContext): ProviderAdapter | null {
  return allAdapters(context).find((adapter) => adapter.id === id) ?? null;
}

export const SUPPORTED_PROVIDERS: ProviderId[] = ["chatgpt", "claude", "deepseek", "doubao", "zhipu"];
