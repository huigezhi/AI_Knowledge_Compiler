/**
 * Universal Conversation Schema — v1
 * ---------------------------------------------------------------------------
 * 单一事实来源。TypeScript 类型定义在这里，Python (`apps/backend/akc/schemas`)
 * 与 JSON Schema (`packages/schema/schema/*.json`) 必须与本文件保持同步。
 *
 * 变更此文件 = 变更 SCHEMA_VERSION + 提供数据库迁移。
 */

export const SCHEMA_VERSION = "1.0.0";

export type ProviderId =
  | "chatgpt"
  | "claude"
  | "deepseek"
  | "doubao"
  | "zhipu"
  | (string & Record<never, never>);

export type MessageRole = "user" | "assistant" | "system" | "tool" | "unknown";

export type ContentBlock =
  | { type: "text"; text: string }
  | { type: "code"; language?: string; text: string }
  | { type: "image"; local_ref?: string; source_url?: string }
  | { type: "file"; local_ref?: string; name?: string; mime?: string };

export interface Message {
  id: string;
  provider_message_id?: string;
  conversation_id: string;
  role: MessageRole;
  content: ContentBlock[];
  sequence: number;
  created_at?: string;
  parent_message_id?: string;
  model?: string;
  metadata?: Record<string, unknown>;
  content_hash: string;
}

export interface Conversation {
  id: string;
  provider: ProviderId;
  provider_conversation_id: string;
  title: string;
  url?: string;
  model?: string;
  created_at?: string;
  updated_at?: string;
  tags?: string[];
  messages: Message[];
  raw_payload_ref?: string;
  content_hash: string;
  /** Schema 版本。缺省视为 "1.0.0"。 */
  schema_version?: string;
  /** 采集该会话的 adapter 版本，用于问题复现。 */
  adapter_version?: string;
}

/** 历史列表项（不含消息体）。 */
export interface ConversationSummary {
  provider_conversation_id: string;
  title: string;
  url?: string;
  updated_at?: string;
  message_count?: number;
}

export type PageKind = "conversation" | "history" | "unknown";

export type AdapterHealthStatus = "healthy" | "degraded" | "unhealthy";

export interface AdapterHealth {
  provider: ProviderId;
  status: AdapterHealthStatus;
  /** 页面结构指纹，用于检测第三方 DOM 变化。 */
  dom_version?: string;
  message?: string;
  checked_at: string;
}

export interface ListOptions {
  limit?: number;
  /** 虚拟列表场景下向上滚动的最大次数。 */
  maxScrolls?: number;
  signal?: AbortSignal;
}

/** 统一 Adapter 接口：所有平台必须实现，禁止在业务代码里出现 selector。 */
export interface ProviderAdapter {
  readonly id: ProviderId;
  readonly adapterVersion: string;
  matches(url: string): boolean;
  detectPage(): PageKind;
  listConversations(options?: ListOptions): Promise<ConversationSummary[]>;
  fetchConversation(id: string): Promise<Conversation>;
  fetchCurrentConversation(): Promise<Conversation>;
  healthCheck(): Promise<AdapterHealth>;
}

/** 知识类型 taxonomy（需求文档 §8.2）。 */
export const KNOWLEDGE_TYPES = [
  "fact",
  "concept",
  "method",
  "heuristic",
  "decision",
  "question",
  "hypothesis",
  "opinion",
] as const;

export type KnowledgeType = (typeof KNOWLEDGE_TYPES)[number];

/** 知识生命周期状态（需求文档 §8.3）。 */
export const KNOWLEDGE_STATUSES = [
  "candidate",
  "review",
  "verified",
  "rejected",
  "merged",
  "archived",
] as const;

export type KnowledgeStatus = (typeof KNOWLEDGE_STATUSES)[number];

/** Merge Planner 动作（需求文档 §9.4）。 */
export const MERGE_ACTIONS = ["create", "update", "merge", "ignore", "review"] as const;

export type MergeAction = (typeof MERGE_ACTIONS)[number];
