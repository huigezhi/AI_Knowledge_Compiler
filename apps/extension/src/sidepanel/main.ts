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
  /** 最近一次编译产出的知识 id（「一键写入 Obsidian」只写这批，不是全部知识）。 */
  lastCompileKnowledgeIds: string[];
  /** Obsidian 写入目标（供用户确认文件会落到哪里）。 */
  vault: { configured: boolean; vault_path: string | null; knowledge_folder: string } | null;
  lastAction: (() => Promise<void>) | null;
}

const state: State = {
  settings: (await loadSettings()) as ExtensionSettings,
  api: new AkcApiClient({ backendUrl: "", authToken: "" }),
  provider: null,
  history: [],
  lastConversationId: null,
  knowledgeIds: [],
  lastCompileKnowledgeIds: [],
  vault: null,
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

/** 平台识别结果（供健康检查等调用方复用）。 */
interface ActiveDetection {
  provider: ProviderId | null;
  label: string;
  page: string | null;
  note: string;
}

/**
 * 实时识别**当前活动标签页**。
 *
 * 以前只在面板打开时探测一次，且后台会回退到"最近用过的平台页"——
 * 于是用户切到别的页面后，面板永远停在上一次的结果，看起来像坏了。
 * 现在走 AKC/DETECT_ACTIVE（只认活动标签页，不回退），并监听标签页切换/加载。
 */
async function detectActive(): Promise<ActiveDetection> {
  const response = await toBackground({ type: "AKC/DETECT_ACTIVE" });
  if (!response.ok) {
    const note =
      response.code === "CONTENT_SCRIPT_STALE"
        ? "扩展刚更新：刷新平台页面（F5）后即可"
        : response.code === "NOT_PLATFORM_PAGE"
          ? "当前页面不是受支持的聊天平台"
          : response.message;
    state.provider = null;
    setText("provider-name", "未检测到会话");
    setText("conversation-title", "—");
    setText("adapter-health", note);
    return { provider: null, label: "未检测到会话", page: null, note };
  }
  if (!("provider" in response)) {
    return { provider: null, label: "未检测到会话", page: null, note: "探测结果不完整" };
  }

  state.provider = response.provider;
  const label = response.provider
    ? (PROVIDER_LABEL[response.provider] ?? response.provider)
    : "不支持的平台";
  // 扩展更新后旧页面里的内容脚本会失联：此时后台退回了 URL 判定结果，
  // 平台名是对的，但采集要等页面刷新一次 —— 必须把这个动作讲清楚
  const staleSuffix = response.stale ? "（刷新本页 F5 后即可采集）" : "";
  setText("provider-name", `${label}${staleSuffix}`);
  setText("conversation-title", response.page === "conversation" ? "（当前会话页）" : "（不在会话详情页）");

  const health = await toBackground({ type: "AKC/HEALTH_CHECK" });
  let note = "—";
  if (health.ok && "health" in health) {
    const statusLabel = { healthy: "正常", degraded: "降级", unhealthy: "异常" }[health.health.status];
    note = `${statusLabel} · ${health.health.message ?? ""} · ${health.health.dom_version ?? ""}`.trim();
  } else if ("message" in health) {
    note = health.message || "适配器体检失败";
  }
  setText("adapter-health", note);
  return { provider: response.provider, label, page: response.page, note };
}

/** 切标签页 / 页面加载完成后自动重识别（去抖，避免频繁打扰内容脚本）。 */
function watchActiveTab(): void {
  let timer: number | undefined;
  const schedule = (): void => {
    if (timer !== undefined) clearTimeout(timer);
    timer = window.setTimeout(() => void detectActive(), 400);
  };
  chrome.tabs?.onActivated?.addListener(schedule);
  chrome.tabs?.onUpdated?.addListener((_tabId, changeInfo) => {
    if (changeInfo.status === "complete") schedule();
  });
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

async function loadHistory(options: { silent?: boolean } = {}): Promise<void> {
  clearError();
  const response = await toBackground({ type: "AKC/LIST_CONVERSATIONS" });
  if (!response.ok) {
    if (!options.silent) showError(response.message, loadHistory);
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

/**
 * 「自动同步历史」：走后台静默同步（AKC/SYNC_HISTORY_NOW）。
 *
 * 以前走的是导航式遍历（AKC/CRAWL_START）——后台会在这个标签页里**逐个打开每个
 * 历史会话**，页面疯狂跳转、既卡顿又有平台账号风控风险。现在改为内容脚本同源
 * 抓取会话页并离线解析，页面完全不动；去重、节流、重试次数与连续失败熔断都在后台。
 */
async function startCrawl(): Promise<void> {
  clearError();
  const response = await toBackground({ type: "AKC/SYNC_HISTORY_NOW" });
  if (!response.ok) {
    // 「刚同步过」「已有任务在进行中」这类不是故障：给提示而不是红色错误横幅
    if (response.code === "SYNC_NOT_STARTED") {
      setText("sync-status", `未开始：${response.message}`);
      return;
    }
    showError(response.message, startCrawl);
    return;
  }
  setText("sync-status", "后台静默同步已开始…（不跳转页面，可继续正常使用）");
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
  el<HTMLButtonElement>("btn-write-current").disabled = true;
  try {
    const job = await state.api.createCompileJob(conversationId);
    const finished = await pollJob(job.id);
    // 记住本次产出的知识 id：「一键写入 Obsidian」只写这批，而不是全库重写一遍
    state.lastCompileKnowledgeIds = collectCompileResult(finished);
    el<HTMLButtonElement>("btn-write-current").disabled = state.lastCompileKnowledgeIds.length === 0;
    await refreshKnowledge();
    await autoWriteToObsidian();
    renderWriteTarget();
  } catch (error) {
    showError(humanizeError(error), () => startCompile(conversationId));
  }
}

/** 编译成功后自动落盘。

 编译只写数据库；不调用 obsidian/sync 的话，Obsidian 仓库里一个文件都不会出现——
 用户看到的就是"编译成功了，但我的知识在哪？"。这里把这一步接上，省掉
 "编译完还得记得再点一次写入"的隐性操作。写入是幂等的（按内容哈希比对），
 重复执行不会覆盖用户在 Obsidian 里的手工修改。
 */
async function autoWriteToObsidian(): Promise<void> {
  if (state.knowledgeIds.length === 0) return;
  try {
    const result = await state.api.syncObsidian({ knowledge_ids: state.knowledgeIds });
    const skipped = result.skipped.length ? ` · 跳过 ${result.skipped.length} 个（冲突）` : "";
    setText("sync-status", `已编译并写入 Obsidian：${result.written.length} 个文件${skipped}`);
  } catch (error) {
    // 落盘失败不该推翻"编译成功"的结论，降级为提示而不是红色错误横幅。
    setText("sync-status", `编译成功，但写入 Obsidian 失败：${humanizeError(error)}`);
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

// ------------------------------------------------------------------ 健康检查
/**
 * 「健康检查」：一次点掉四处不确定性，并把结论明确写出来。
 *
 * 以前这个按钮只是重新读一次平台，既没有加载态也没有结论，点了像没点。
 * 现在依次检查后端服务 / Obsidian 库 / AI 编译配置 / 当前页面适配器，
 * 逐项给出结果，无异常也明确说"全部正常"。
 */
async function runHealthCheck(): Promise<void> {
  const button = el<HTMLButtonElement>("btn-health");
  button.disabled = true;
  setText("health-result", "检查中…");
  clearError();

  const lines: string[] = [];
  let problems = 0;

  // 1) 后端服务
  try {
    const health = await state.api.health();
    lines.push(`后端服务 ${health.status === "ok" ? "正常" : "异常"}（v${health.version}）`);
    if (health.status !== "ok") problems += 1;
  } catch (error) {
    lines.push(`后端服务不可达：${humanizeError(error)}`);
    problems += 1;
  }

  // 2) Obsidian 库
  try {
    const vault = await state.api.obsidianStatus();
    state.vault = vault;
    lines.push(
      vault.configured
        ? `Obsidian 库已连接（${vault.vault_path} · 知识目录 ${vault.knowledge_folder}）`
        : "Obsidian 库未连接（双击 scripts\\windows\\set-vault.bat 选择即可）",
    );
    if (!vault.configured) problems += 1;
    renderWriteTarget();
  } catch (error) {
    lines.push(`Obsidian 状态读取失败：${humanizeError(error)}`);
    problems += 1;
  }

  // 3) AI 编译配置
  try {
    const llm = await state.api.llmStatus();
    lines.push(
      llm.llm_enabled && llm.llm_model
        ? `AI 编译已启用（${llm.llm_provider ?? "unknown"} / ${llm.llm_model}）`
        : "AI 编译未配置（只会保存原始对话，不会生成知识笔记）",
    );
    if (!llm.llm_enabled) problems += 1;
  } catch (error) {
    lines.push(`AI 编译状态读取失败：${humanizeError(error)}`);
    problems += 1;
  }

  // 4) 当前页面适配器（顺带把平台识别刷新成最新的）
  const detected = await detectActive();
  lines.push(
    detected.provider
      ? `当前页面 ${detected.label}${detected.page === "conversation" ? "（会话页）" : "（非会话详情页）"} · 适配器${detected.note}`
      : `当前页面未识别到受支持平台（${detected.note}）`,
  );
  if (!detected.provider) problems += 1;

  const summary = problems === 0 ? "全部正常" : `发现 ${problems} 项需要处理`;
  setText("health-result", `${summary}：${lines.join("；")}`);
  if (problems > 0) {
    showError(`${summary}：${lines.join("；")}`, runHealthCheck);
  }

  button.disabled = false;
}

// ------------------------------------------------------------------ 一键写入
/** 显示本次编译结果的写入目标（让用户知道文件会落到哪里）。 */
function renderWriteTarget(): void {
  const node = el("write-target");
  if (!state.vault?.configured) {
    node.textContent = "Obsidian 库未连接：先双击 scripts\\windows\\set-vault.bat 连接，再写入。";
    return;
  }
  const base = `${state.vault.vault_path}\\${state.vault.knowledge_folder}`;
  if (state.lastCompileKnowledgeIds.length === 0) {
    node.textContent = `写入目标：${base}\\<主题域>\\（先「保存 + 编译」一次，这里即可一键写入）`;
    return;
  }
  node.textContent = `本次编译 ${state.lastCompileKnowledgeIds.length} 条 · 写入目标：${base}\\<主题域>\\`;
}

/** 从编译任务结果里取出本次产出的知识 id。 */
function collectCompileResult(job: JobView): string[] {
  const raw = job.result?.knowledge_ids;
  if (!Array.isArray(raw)) return [];
  return raw.map(String).filter(Boolean);
}

/** 一键写入 Obsidian：只写本次编译结果，失败自动重试 2 次。 */
async function writeCurrentToObsidian(): Promise<void> {
  clearError();
  const button = el<HTMLButtonElement>("btn-write-current");
  const ids = state.lastCompileKnowledgeIds;
  if (ids.length === 0) {
    setText("write-target", "还没有本次编译结果：先点「保存 + 编译」，再一键写入。");
    return;
  }
  if (!state.vault?.configured) {
    showError("Obsidian 库未连接：先双击 scripts\\windows\\set-vault.bat 连接一次。", writeCurrentToObsidian);
    return;
  }

  button.disabled = true;
  const original = "一键写入 Obsidian";
  button.textContent = "写入中…";
  try {
    let lastError: unknown = null;
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try {
        const result = await state.api.syncObsidian({ knowledge_ids: ids });
        const skipped = result.skipped.length ? ` · 跳过 ${result.skipped.length} 个（冲突，未覆盖你的手工修改）` : "";
        setText(
          "write-target",
          `已写入 ${result.written.length} 个文件到 ${result.vault_path}${skipped}`,
        );
        setText("sync-status", `已写入 ${result.written.length} 个文件${skipped}`);
        return;
      } catch (error) {
        lastError = error;
        if (attempt < 3) await new Promise((resolve) => setTimeout(resolve, 800 * attempt));
      }
    }
    showError(`写入 Obsidian 失败（已重试 2 次）：${humanizeError(lastError)}`, writeCurrentToObsidian);
  } finally {
    button.textContent = original;
    button.disabled = false;
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
  el("btn-health").addEventListener("click", () => void runHealthCheck());
  el("btn-load-history").addEventListener("click", () => void loadHistory());
  el("btn-crawl").addEventListener("click", () => void startCrawl());
  el("btn-crawl-cancel").addEventListener("click", () => void cancelCrawl());
  el("btn-write-obsidian").addEventListener("click", () => void writeToObsidian());
  el("btn-write-current").addEventListener("click", () => void writeCurrentToObsidian());
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
  // 切标签页 / 页面加载完成后自动重识别平台：面板显示的永远是"用户现在看着的页面"
  watchActiveTab();
  // 历史模块自动加载：打开面板就能看到全部已采集会话，不用再点「加载历史」。
  // 失败静默——面板刚开就弹红条只会吓到用户，点手动加载时自然会看到原因。
  void loadHistory({ silent: true }).catch(() => {});
  await detectActive();
  try {
    await state.api.health();
  } catch (error) {
    showError(humanizeError(error), boot);
    return;
  }
  // 写入目标提示需要知道库在哪；拿不到也不阻塞面板
  state.vault = await state.api.obsidianStatus().catch(() => null);
  renderWriteTarget();
  await refreshCrawlStatus();
  await refreshKnowledge();
}

void boot();
