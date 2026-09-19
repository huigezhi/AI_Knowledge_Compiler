/**
 * Side Panel 主逻辑。
 *
 * 交互原则（需求文档 §14.2）：
 * * 同步中：显示「已处理 / 总数、成功 / 失败」；
 * * 编译中：显示阶段（Extract / Link / Merge / Write），**不显示虚假百分比**；
 * * 失败：提供 retry 与错误详情；
 * * 合并：显示来源与置信度。
 */

import type { Conversation, ConversationSummary, ProviderId } from "@akc/schema";
import { AkcApiClient, ApiError, OfflineError, type JobView, type KnowledgeView } from "@/shared/api-client";
import { logger, setLogLevel } from "@/shared/logger";
import type { MessageResponse } from "@/shared/messaging";
import { loadSettings, type ExtensionSettings } from "@/shared/settings";

const PROVIDER_LABEL: Record<string, string> = {
  chatgpt: "ChatGPT",
  claude: "Claude",
  deepseek: "DeepSeek",
  doubao: "豆包",
  zhipu: "智谱清言",
};

const STAGE_LABEL: Record<string, string> = {
  pending: "排队中",
  extract: "抽取知识",
  link: "关联已有知识",
  merge: "合并去重",
  write: "写入知识库",
};

interface State {
  settings: ExtensionSettings;
  api: AkcApiClient;
  provider: ProviderId | null;
  history: ConversationSummary[];
  selected: Set<string>;
  lastConversationId: string | null;
  knowledgeIds: string[];
  lastAction: (() => Promise<void>) | null;
}

const state: State = {
  settings: (await loadSettings()) as ExtensionSettings,
  api: new AkcApiClient({ backendUrl: "", authToken: "" }),
  provider: null,
  history: [],
  selected: new Set(),
  lastConversationId: null,
  knowledgeIds: [],
  lastAction: null,
};

// ------------------------------------------------------------------ DOM 辅助
function el<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`missing element: #${id}`);
  return node as T;
}

function showError(message: string, retry: (() => Promise<void>) | null = null): void {
  const banner = el("error-banner");
  el("error-text").textContent = message;
  el<HTMLButtonElement>("btn-retry").hidden = retry === null;
  state.lastAction = retry;
  banner.hidden = false;
}

function clearError(): void {
  el("error-banner").hidden = true;
}

function setText(id: string, value: string): void {
  el(id).textContent = value;
}

// ------------------------------------------------------------------ 页面通信
async function toBackground(payload: Record<string, unknown>): Promise<MessageResponse> {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(payload, (response: MessageResponse | undefined) => {
      resolve(response ?? { ok: false, code: "NO_RESPONSE", message: "后台脚本未响应" });
    });
  });
}

async function detectProvider(): Promise<void> {
  const response = await toBackground({ type: "AKC/DETECT_PAGE" });
  if (!response.ok) {
    setText("provider-name", "未检测到会话");
    return;
  }
  if (!("provider" in response)) return;
  state.provider = response.provider;
  setText("provider-name", response.provider ? (PROVIDER_LABEL[response.provider] ?? response.provider) : "不支持的平台");
  setText("conversation-title", response.page === "conversation" ? "（当前会话页）" : "（不在会话详情页）");

  const health = await toBackground({ type: "AKC/HEALTH_CHECK" });
  if (health.ok && "health" in health) {
    const label = { healthy: "正常", degraded: "降级", unhealthy: "异常" }[health.health.status];
    const domVersion = health.health.dom_version ?? "";
    setText("adapter-health", `${label} · ${health.health.message ?? ""} · ${domVersion}`.trim());
  }
}

// ------------------------------------------------------------------ 采集
async function fetchCurrentConversation(): Promise<Conversation> {
  const response = await toBackground({ type: "AKC/FETCH_CURRENT" });
  if (!response.ok) throw new Error(response.message);
  if (!("conversation" in response)) throw new Error("content script 未返回会话数据");
  return response.conversation;
}

async function saveCurrent(withCompile: boolean): Promise<void> {
  clearError();
  try {
    const conversation = await fetchCurrentConversation();
    const result = await state.api.importConversation(conversation, {
      write_raw_to_obsidian: state.settings.writeRawToObsidian,
      compile: false,
    });
    state.lastConversationId = result.conversation_id;
    setText(
      "sync-status",
      `已保存：${result.created ? "新建" : "更新"} · ${result.created_messages} 条新增消息 · ${result.updated_messages} 条更新`,
    );
    if (withCompile) await startCompile(result.conversation_id);
  } catch (error) {
    showError(humanizeError(error), () => saveCurrent(withCompile));
  }
}

async function loadHistory(): Promise<void> {
  clearError();
  const response = await toBackground({ type: "AKC/LIST_CONVERSATIONS" });
  if (!response.ok) {
    showError(response.message, loadHistory);
    return;
  }
  if (!("items" in response)) return;
  state.history = response.items;
  state.selected.clear();
  renderHistory();
  setText("sync-status", `已加载 ${state.history.length} 条历史会话`);
}

function renderHistory(): void {
  const list = el<HTMLUListElement>("history-list");
  list.innerHTML = "";
  for (const item of state.history) {
    const li = document.createElement("li");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selected.has(item.provider_conversation_id);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selected.add(item.provider_conversation_id);
      else state.selected.delete(item.provider_conversation_id);
    });
    const label = document.createElement("span");
    label.textContent = item.title;
    li.append(checkbox, label);
    list.append(li);
  }
}

async function batchSync(): Promise<void> {
  clearError();
  if (state.selected.size === 0) {
    showError("请先勾选要同步的历史会话");
    return;
  }
  const targets = state.history.filter((item) => state.selected.has(item.provider_conversation_id));
  let ok = 0;
  let failed = 0;
  const batch = targets.slice(0, state.settings.batchSize);
  const run = await state.api.createSyncRun(String(state.provider ?? "unknown"), [
    ...state.selected,
  ]);
  for (const [index, item] of batch.entries()) {
    setText("sync-status", `同步中：${index + 1}/${batch.length} · 成功 ${ok} · 失败 ${failed}`);
    try {
      const conversation = await fetchConversationById(item.provider_conversation_id);
      await state.api.importConversation(conversation, {
        write_raw_to_obsidian: state.settings.writeRawToObsidian,
        compile: false,
      });
      ok += 1;
    } catch (error) {
      failed += 1;
      logger.warn("batch_sync_item_failed", { id: item.provider_conversation_id, error: String(error) });
    }
  }
  await state.api.finishSyncRun(run.id, { total: batch.length, ok, failed });
  setText("sync-status", `同步完成：成功 ${ok} · 失败 ${failed} · 共 ${batch.length} 条`);
  if (failed > 0) showError(`${failed} 条同步失败，原始数据未受影响，可重试。`, batchSync);
}

/**
 * 批量同步取会话。
 *
 * 有的平台（智谱清言）历史列表里没有任何会话 ID，只能用 `title:<标题>` 占位 ID，
 * 因此除了 ID 相等，还接受「标题相等」的匹配。
 */
async function fetchConversationById(id: string): Promise<Conversation> {
  const response = await toBackground({ type: "AKC/FETCH_CURRENT" });
  if (!response.ok) throw new Error(response.message);
  if (!("conversation" in response)) throw new Error("content script 未返回会话数据");
  const conversation = response.conversation;
  const expectedTitle = id.startsWith("title:") ? id.slice("title:".length) : null;
  const matched = expectedTitle
    ? conversation.title === expectedTitle
    : conversation.provider_conversation_id === id;
  if (!matched) {
    throw new Error(
      expectedTitle
        ? `请先打开标题为「${expectedTitle}」的会话再同步（当前是「${conversation.title}」）`
        : `请先打开会话 ${id} 再同步（当前页面是 ${conversation.provider_conversation_id}）`,
    );
  }
  return conversation;
}

// ------------------------------------------------------------------ 编译
async function startCompile(conversationId: string): Promise<void> {
  clearError();
  try {
    const job = await state.api.createCompileJob(conversationId);
    await pollJob(job.id);
    await refreshKnowledge();
  } catch (error) {
    showError(humanizeError(error), () => startCompile(conversationId));
  }
}

/** 轮询任务状态：展示真实阶段，而不是伪造进度条。 */
async function pollJob(jobId: string): Promise<JobView> {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const job = await state.api.getJob(jobId);
    const stage = job.stage ? (STAGE_LABEL[job.stage] ?? job.stage) : "准备中";
    setText("job-stage", `任务 ${job.status} · 阶段：${stage} · 已尝试 ${job.attempts}/${job.max_attempts}`);
    if (job.status === "succeeded") return job;
    if (job.status === "failed" || job.status === "cancelled") {
      throw new Error(job.error ?? "编译任务失败");
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  throw new Error("编译超时，请到任务列表查看状态");
}

async function refreshKnowledge(): Promise<void> {
  const result = await state.api.listKnowledge({ limit: 50 });
  state.knowledgeIds = result.items.map((item) => item.id);
  setText("stat-items", String(result.items.length));
  setText(
    "stat-review",
    String(result.items.filter((item) => item.status === "review").length),
  );
  setText(
    "stat-created",
    String(result.items.filter((item) => item.status !== "review").length),
  );
  renderKnowledge(result.items);
}

function renderKnowledge(items: KnowledgeView[]): void {
  const list = el<HTMLUListElement>("knowledge-list");
  list.innerHTML = "";
  for (const item of items) {
    const li = document.createElement("li");
    li.className = "knowledge-item";
    const title = document.createElement("div");
    title.className = "knowledge-title";
    title.textContent = `${item.title} · ${item.knowledge_type} · ${item.status}`;
    const meta = document.createElement("div");
    meta.className = "muted";
    meta.textContent = `置信度 ${item.confidence.toFixed(2)} · 来源 ${item.source_message_ids.length} 条 · v${item.version}`;
    li.append(title, meta);

    if (item.status === "review" || item.status === "candidate") {
      const verify = document.createElement("button");
      verify.className = "ghost";
      verify.textContent = "确认";
      verify.addEventListener("click", () => {
        void state.api.reviewKnowledge(item.id, "verify").then(refreshKnowledge).catch((error) => showError(humanizeError(error)));
      });
      li.append(verify);
    }
    list.append(li);
  }
}

async function writeToObsidian(): Promise<void> {
  clearError();
  try {
    const result = await state.api.syncObsidian({ knowledge_ids: state.knowledgeIds });
    setText("sync-status", `已写入 ${result.written.length} 个文件，跳过 ${result.skipped.length} 个（冲突）`);
  } catch (error) {
    showError(humanizeError(error), writeToObsidian);
  }
}

// ------------------------------------------------------------------ 错误映射
function humanizeError(error: unknown): string {
  if (error instanceof OfflineError) return error.message;
  if (error instanceof ApiError) return error.userMessage;
  if (error instanceof Error) return error.message;
  return String(error);
}

// ------------------------------------------------------------------ 启动
function wire(): void {
  el("btn-save").addEventListener("click", () => void saveCurrent(false));
  el("btn-save-compile").addEventListener("click", () => void saveCurrent(true));
  el("btn-health").addEventListener("click", () => void detectProvider());
  el("btn-load-history").addEventListener("click", () => void loadHistory());
  el("btn-sync").addEventListener("click", () => void batchSync());
  el("btn-select-all").addEventListener("click", () => {
    state.selected = new Set(state.history.map((item) => item.provider_conversation_id));
    renderHistory();
  });
  el("btn-write-obsidian").addEventListener("click", () => void writeToObsidian());
  el("btn-retry").addEventListener("click", () => {
    if (state.lastAction) void state.lastAction();
  });
}

async function boot(): Promise<void> {
  state.settings = await loadSettings();
  setLogLevel(state.settings.logLevel);
  state.api = new AkcApiClient({
    backendUrl: state.settings.backendUrl,
    authToken: state.settings.authToken,
  });
  wire();
  await detectProvider();
  try {
    await state.api.health();
  } catch (error) {
    showError(humanizeError(error), boot);
    return;
  }
  await refreshKnowledge();
}

void boot();
