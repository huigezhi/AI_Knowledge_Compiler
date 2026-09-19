/**
 * 类型化 API 客户端。
 *
 * 约定（对应前端边界处理规范）：
 * * 4xx → 映射为可读文案，**不重试**；
 * * 5xx / 网络失败 → 指数退避重试，最多 3 次；
 * * 全部失败 → 抛出 ``OfflineError``，UI 显示离线提示；
 * * 所有写请求自动附带 ``X-AKC-Token``（本地随机令牌，防伪造本地请求）。
 */

import type { Conversation, ConversationSummary, KnowledgeStatus, Message } from "@akc/schema";

export interface ApiErrorPayload {
  code: string;
  message: string;
  retryable: boolean;
  details?: Record<string, unknown>;
}

const HTTP_MESSAGE: Record<number, string> = {
  400: "请求参数有误，后端拒绝了这次操作。",
  401: "本地服务的访问令牌无效，请在设置里重新填写。",
  403: "本地服务拒绝了该请求。",
  404: "找不到对应的资源。",
  409: "目标文件与本地已有内容冲突，已跳过写入。",
  422: "数据不符合 Universal Conversation Schema。",
  500: "本地服务内部错误，请查看后端日志。",
  503: "本地服务尚未就绪。",
};

/**
 * 后端错误码 → 面向用户的中文提示；返回 null 表示没有对应文案。
 *
 * 必须**集中在这里**：同一批错误码会经两条完全不同的路径到达用户 ——
 *   1. HTTP 错误响应（ApiError.userMessage）
 *   2. 异步任务失败（GET /jobs/{id} 的 error_code + error）
 * 只覆盖其中一条，另一条就会把后端的英文原文直接甩给用户（看不懂、也不知道该点哪里）。
 */
export function humanizeBackendCode(code?: string | null): string | null {
  switch (code) {
    case "OBSIDIAN_VAULT_NOT_CONFIGURED":
      // Vault 路径是**后端**（电脑上的 .env）配置，不在本扩展设置页里，
      // 因此文案必须指向正确的位置，否则用户会像无头苍蝇一样在设置页里找。
      return "还没连接 Obsidian 库。请在电脑上双击 scripts\\windows\\set-vault.bat 选择你的库，然后重试。";
    case "SCHEMA_VALIDATION_FAILED":
      return "采集结果不符合数据规范，可能是平台页面结构变化，请更新适配器后再试。";
    case "CLAUDE_DISABLED":
    case "COMPILER_DISABLED":
    case "LLM_DISABLED":
      // 「AI 编译」不是必须的：默认只保存原始对话。要生成知识笔记才需要配 LLM。
      return "还没启用 AI 编译（保存原始对话不需要它）。若要提炼知识，请双击 scripts\\windows\\set-llm.bat 配置模型服务（支持 DeepSeek / Claude），它会自动写入配置并重启后端。";
    case "CLAUDE_REQUEST_FAILED":
      return "调用 AI 编译服务失败（网络/鉴权/限流）。请检查 .env 里的 AKC_LLM_BASE_URL、AKC_LLM_API_KEY 与 AKC_LLM_MODEL，并确认网络可达。";
    case "CLAUDE_OUTPUT_INVALID":
      return "AI 返回的内容不是合法 JSON，已丢弃本次结果（不会写入脏数据）。可重试或换用更强的模型。";
    case "NOT_FOUND":
      return "找不到对应记录，它可能已被删除。";
    default:
      return null;
  }
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly payload: ApiErrorPayload | null,
    readonly requestId?: string,
  ) {
    super(payload?.message ?? HTTP_MESSAGE[status] ?? `请求失败（HTTP ${status}）`);
    this.name = "ApiError";
  }

  /** 面向用户的中文文案：后端英文 message → 可读提示。 */
  get userMessage(): string {
    const mapped = humanizeBackendCode(this.payload?.code);
    if (mapped) return mapped;
    if (this.status === 401) {
      return HTTP_MESSAGE[401]!;
    }
    return this.message;
  }
}

export class OfflineError extends Error {
  constructor(readonly cause?: unknown) {
    super("无法连接本地 AKC 服务，请确认后端已启动（默认 127.0.0.1:38127）。");
    this.name = "OfflineError";
  }
}

export interface BackendSettings {
  backendUrl: string;
  authToken: string;
}

export interface ImportResult {
  conversation_id: string;
  created: boolean;
  created_messages: number;
  updated_messages: number;
  content_hash: string;
  obsidian_path: string | null;
  job_id: string | null;
  warnings: string[];
}

export interface JobView {
  id: string;
  job_type: string;
  status: "pending" | "running" | "succeeded" | "failed" | "cancelled";
  attempts: number;
  max_attempts: number;
  stage: string | null;
  error: string | null;
  error_code: string | null;
  result: Record<string, unknown>;
}

export interface KnowledgeView {
  id: string;
  slug: string;
  title: string;
  status: KnowledgeStatus;
  knowledge_type: string;
  summary: string;
  confidence: number;
  source_message_ids: string[];
  obsidian_path: string | null;
  version: number;
}

/**
 * 后端 `/conversations` 返回的会话条目。
 *
 * 字段名必须与后端一致（后端用 `provider` + `provider_conversation_id`）；
 * 早期这里写成了 `provider_id` / `external_id`，与实际响应不符，
 * 会让「按 provider_conversation_id 去重」之类的逻辑静默拿不到值。
 */
export interface ConversationView {
  id: string;
  provider: string;
  provider_conversation_id: string;
  title: string;
  url: string | null;
  content_hash: string;
  created_at?: string;
  updated_at?: string;
  message_count?: number;
  messages?: Message[];
}

export class AkcApiClient {
  constructor(private settings: BackendSettings) {}

  withSettings(settings: BackendSettings): AkcApiClient {
    return new AkcApiClient(settings);
  }

  // ------------------------------------------------------------------ 端点
  health() {
    return this.request<{ status: string; version: string; schema_version: string }>("/health");
  }

  providers() {
    return this.request<{ items: Array<Record<string, unknown>>; count: number }>("/providers");
  }

  importConversation(conversation: Conversation, options: { write_raw_to_obsidian?: boolean; compile?: boolean } = {}) {
    return this.request<ImportResult>("/conversations/import", {
      method: "POST",
      body: { conversation, options },
    });
  }

  listConversations(params: { provider?: string; q?: string; limit?: number; offset?: number } = {}) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) query.set(key, String(value));
    }
    return this.request<{ items: ConversationView[]; total: number }>(
      `/conversations?${query.toString()}`,
    );
  }

  getConversation(id: string) {
    return this.request<ConversationView>(`/conversations/${encodeURIComponent(id)}`);
  }

  createCompileJob(conversationId: string) {
    return this.request<JobView>("/jobs/compile", {
      method: "POST",
      body: { conversation_id: conversationId },
    });
  }

  getJob(id: string) {
    return this.request<JobView>(`/jobs/${encodeURIComponent(id)}`);
  }

  listKnowledge(params: { status?: KnowledgeStatus; q?: string; limit?: number } = {}) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) query.set(key, String(value));
    }
    return this.request<{ items: KnowledgeView[]; total: number }>(`/knowledge?${query.toString()}`);
  }

  reviewKnowledge(id: string, action: "verify" | "reject" | "archive" | "review", reason = "") {
    return this.request<KnowledgeView>(`/knowledge/${encodeURIComponent(id)}/review`, {
      method: "POST",
      body: { action, reason },
    });
  }

  mergeKnowledge(id: string, targetKnowledgeId: string, reason = "") {
    return this.request<Record<string, unknown>>(`/knowledge/${encodeURIComponent(id)}/merge`, {
      method: "POST",
      body: { target_knowledge_id: targetKnowledgeId, reason },
    });
  }

  /** Obsidian 连接状态：vault 路径是否已配置。 */
  obsidianStatus() {
    return this.request<{
      vault_path: string | null;
      configured: boolean;
      raw_folder: string;
      knowledge_folder: string;
      inbox_folder: string;
    }>("/obsidian/status");
  }

  /** 后端侧的模型服务配置（LLM_*；旧版 CLAUDE_* 值相同，这里只读新键）。 */
  llmStatus() {
    return this.request<{
      llm_enabled: boolean;
      llm_provider: string | null;
      llm_model: string | null;
      llm_api_key_configured: boolean;
    }>("/settings").then((raw) => {
      const values = (raw as { values?: Record<string, unknown> }).values ?? {};
      return {
        llm_enabled: Boolean(values.llm_enabled ?? false),
        llm_provider: (values.llm_provider as string | null) ?? null,
        llm_model: (values.llm_model as string | null) ?? null,
        llm_api_key_configured: Boolean(
          (raw as { llm_api_key_configured?: boolean }).llm_api_key_configured ?? false,
        ),
      };
    });
  }

  syncObsidian(payload: { knowledge_ids?: string[]; conversation_ids?: string[] }) {
    return this.request<{
      written: Array<{ id: string; path: string; changed: boolean }>;
      skipped: Array<{ id: string; reason: string }>;
      vault_path: string;
    }>("/obsidian/sync", { method: "POST", body: payload });
  }

  getSettings() {
    return this.request<{ values: Record<string, unknown> }>("/settings");
  }

  updateSettings(values: Record<string, unknown>) {
    return this.request<{ updated: string[]; rejected: string[] }>("/settings", {
      method: "PUT",
      body: { values },
    });
  }

  createSyncRun(provider: string, conversationIds: string[] = []) {
    return this.request<{ id: string; provider: string; status: string }>("/sync-runs", {
      method: "POST",
      body: { provider, conversation_ids: conversationIds },
    });
  }

  finishSyncRun(id: string, stats: Record<string, number>, error?: string) {
    const query = new URLSearchParams({ status: error ? "failed" : "succeeded" });
    if (error) query.set("error", error);
    return this.request<{ id: string; status: string; stats: Record<string, number> }>(
      `/sync-runs/${encodeURIComponent(id)}/finish?${query.toString()}`,
      { method: "POST", body: stats },
    );
  }

  // ------------------------------------------------------------------ 内部
  private async request<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
    const url = `${this.settings.backendUrl.replace(/\/$/, "")}/api/v1${path}`;
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (this.settings.authToken) headers["X-AKC-Token"] = this.settings.authToken;

    let lastError: unknown;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        const response = await fetch(url, {
          method: init.method ?? "GET",
          headers,
          body: init.body === undefined ? undefined : JSON.stringify(init.body),
        });

        if (response.ok) {
          return (await response.json()) as T;
        }

        const payload = (await response.json().catch(() => null)) as
          | { error?: ApiErrorPayload; request_id?: string }
          | null;
        const apiError = new ApiError(
          response.status,
          payload?.error ?? null,
          payload?.request_id,
        );
        // 4xx 不重试（客户端错误重试无意义）
        if (response.status < 500) throw apiError;
        lastError = apiError;
      } catch (error) {
        if (error instanceof ApiError && error.status < 500) throw error;
        lastError = error;
      }
      await sleep(300 * 2 ** attempt); // 指数退避：300ms / 600ms / 1200ms
    }
    throw lastError instanceof ApiError ? lastError : new OfflineError(lastError);
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export type { Conversation, ConversationSummary };
