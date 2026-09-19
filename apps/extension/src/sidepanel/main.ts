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
import {
  AkcApiClient,
  ApiError,
  humanizeBackendCode,
  OfflineError,
  type JobView,
  type KnowledgeView,
} from "@/shared/api-client";
import { setLogLevel } from "@/shared/logger";
import { isMessage, type CrawlProgress, type MessageResponse } from "@/shared/messaging";
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
  lastConversationId: string | null;
  knowledgeIds: string[];
  lastAction: (() => Promise<void>) | null;
}

const state: State = {
  settings: (await loadSettings()) as ExtensionSettings,
  api: new AkcApiClient({ backendUrl: "", authToken: "" }),
  provider: null,
  history: [],
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
  // 空消息不允许渲染成一块没有文字的红条：那比不提示更糟（用户完全不知道发生了什么）。
  // 已知来源：后端任务失败的 error 字段可能为空串（`new Error("")`）。
  const text = (message ?? "").trim();
  el("error-text").textContent =
    text || "发生了未知错误。请点「重试」；若反复出现，请重新打开侧边栏，并告诉我当时的操作。";
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
    setText(
      "adapter-health",
      response.code === "CONTENT_SCRIPT_STALE"
        ? "扩展刚更新：刷新平台页面（F5）后即可"
        : "请打开豆包 / DeepSeek / ChatGPT 等聊天页面",
    );
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
  renderHistory();
  setText("sync-status", `已加载 ${state.history.length} 条历史会话`);
}

function renderHistory(): void {
  const list = el<HTMLUListElement>("history-list");
  list.innerHTML = "";
  for (const item of state.history) {
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = item.title;
    li.append(label);
    list.append(li);
  }
}

// ------------------------------------------------------------------ 自动遍历
function renderCrawlProgress(progress: CrawlProgress): void {
  const cancel = el<HTMLButtonElement>("btn-crawl-cancel");
  const crawlBtn = el<HTMLButtonElement>("btn-crawl");
  cancel.hidden = !progress.running;
  crawlBtn.disabled = progress.running;

  if (!progress.running && progress.done === 0 && !progress.finishedAt) {
    setText("crawl-progress", "");
    renderAutoSaveStatus(progress);
    return;
  }

  if (progress.running) {
    const current = progress.current ? ` · 正在处理「${progress.current}」` : "";
    setText(
      "crawl-progress",
      `同步中：${progress.done}/${progress.total} · 成功 ${progress.ok} · 失败 ${progress.failed}${current}`,
    );
  } else {
    const tail = progress.cancelled
      ? "（已取消）"
      : `完成 · 成功 ${progress.ok} · 失败 ${progress.failed} · 跳过 ${progress.skipped}（已存在）`;
    setText("crawl-progress", `历史同步结束：${tail}`);
    if (progress.failed > 0 && progress.lastError) {
      showError(`有 ${progress.failed} 条未采集成功，最后一条错误：${progress.lastError}`, startCrawl);
    }
  }
  renderAutoSaveStatus(progress);
}

function renderAutoSaveStatus(progress: CrawlProgress): void {
  const node = el("autosave-status");
  if (!state.settings.autoSave) {
    node.textContent = "已关闭（可在设置页开启）";
    node.style.color = "#ffb86b";
    return;
  }
  if (!progress.lastAutoSaveAt) {
    node.textContent = `开启中 · 停手 ${state.settings.autoSaveDelaySeconds} 秒后自动保存`;
    node.style.color = "#9aa4b2";
    return;
  }
  const seconds = Math.max(0, Math.round((Date.now() - progress.lastAutoSaveAt) / 1000));
  const ago = seconds < 60 ? `${seconds} 秒前` : `${Math.round(seconds / 60)} 分钟前`;
  node.textContent = `开启中 · 上次保存 ${ago}${progress.lastAutoSaveTitle ? `（${progress.lastAutoSaveTitle}）` : ""}`;
  node.style.color = "#7ee787";
}

async function startCrawl(): Promise<void> {
  clearError();
  const response = await toBackground({ type: "AKC/CRAWL_START", limit: state.settings.batchSize * 10 });
  if (!response.ok) {
    showError(response.message, startCrawl);
    return;
  }
  if ("crawl" in response) renderCrawlProgress(response.crawl);
}

async function cancelCrawl(): Promise<void> {
  const response = await toBackground({ type: "AKC/CRAWL_CANCEL" });
  if ("crawl" in response) renderCrawlProgress(response.crawl);
}

/** 侧边栏打开时订阅后台推送的进度。 */
function subscribeProgress(): void {
  chrome.runtime.onMessage.addListener((raw) => {
    if (isMessage(raw) && raw.type === "AKC/CRAWL_PROGRESS") {
      renderCrawlProgress(raw.progress);
    }
    return false;
  });
}

async function refreshCrawlStatus(): Promise<void> {
  const response = await toBackground({ type: "AKC/CRAWL_STATUS" });
  if ("crawl" in response) renderCrawlProgress(response.crawl);
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
      // 任务失败要按 error_code 翻译：否则后端的英文原文会直接甩给用户。
      // 注意 `??` 对空串不生效，空 error 字段必须先 trim 再判断。
      const translated = humanizeBackendCode(job.error_code);
      const raw = job.error?.trim() || "编译任务失败（原因未返回，请查看后端任务列表）";
      // 中文指引 + 原始详情都保留：只给中文会丢掉排查线索（比如模型输出片段），
      // 只给英文原文用户又看不懂。
      throw new Error(translated ? `${translated}\n详情：${raw}` : raw);
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
  el("btn-crawl").addEventListener("click", () => void startCrawl());
  el("btn-crawl-cancel").addEventListener("click", () => void cancelCrawl());
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
  subscribeProgress();
  await detectProvider();
  try {
    await state.api.health();
  } catch (error) {
    showError(humanizeError(error), boot);
    return;
  }
  await refreshCrawlStatus();
  await refreshKnowledge();
}

void boot();
