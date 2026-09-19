/**
 * Side Panel 主逻辑。
 *
 * 交互原则（需求文档 §14.2）：
 * * 同步中：显示「已处理 / 总数、成功 / 失败」；
 * * 编译中：显示阶段（Extract / Link / Merge / Write），**不显示虚假百分比**；
 * * 失败：顶部一行小字说明原因（自动收起），重试即再点一次对应按钮，不再挂常驻红条；
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
import { logger, setLogLevel } from "@/shared/logger";
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

/** 知识点状态：用中文说清楚每条现在处于哪一步，别让用户猜 review/verified 是什么。 */
const STATUS_LABEL: Record<string, string> = {
  candidate: "待审核",
  review: "待审核",
  verified: "已确认",
  rejected: "已驳回",
  archived: "已归档",
  merged: "已合并",
  deleted: "已删除",
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
  /** 当前展示的知识点（供审核交互与写入范围计算复用）。 */
  knowledge: KnowledgeView[];
  /** 审核批量操作勾选中的条目 id。 */
  selected: Set<string>;
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
  knowledge: [],
  selected: new Set<string>(),
};

// ------------------------------------------------------------------ DOM 辅助
function el<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`missing element: #${id}`);
  return node as T;
}

/** 提示自动收起的时长：够看清一句话，又不会一直挂在面板顶部。 */
const ERROR_LINE_TTL_MS = 10_000;
let errorLineTimer: number | undefined;

/**
 * 失败提示：一行小字 + 定时自动收起。
 *
 * 这里刻意不再提供「重试」按钮——所有曾经挂在这里的重试动作（保存、加载、
 * 遍历、编译、写入、体检）都等价于**再点一次对应的按钮**，按钮本身一直都在，
 * 因此去掉它不会丢失任何能力；留下的只是一个常驻红条，看着像面板坏了。
 * 文案本身仍然显示，失败不会被静默吞掉，同时也会写进日志便于排查。
 */
function showError(message: string): void {
  const text = (message ?? "").trim();
  const shown =
    text || "操作失败（原因未知）。请再点一次对应按钮；若反复失败，请重新打开侧边栏。";
  logger.error("sidepanel_error", { message: text });
  const line = el("error-line");
  line.textContent = shown;
  line.hidden = false;
  if (errorLineTimer !== undefined) clearTimeout(errorLineTimer);
  errorLineTimer = window.setTimeout(clearError, ERROR_LINE_TTL_MS);
}

function clearError(): void {
  if (errorLineTimer !== undefined) {
    clearTimeout(errorLineTimer);
    errorLineTimer = undefined;
  }
  const line = document.getElementById("error-line");
  if (line) line.hidden = true;
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
    showError(humanizeError(error));
  }
}

async function loadHistory(options: { silent?: boolean } = {}): Promise<void> {
  clearError();
  const response = await toBackground({ type: "AKC/LIST_CONVERSATIONS" });
  if (!response.ok) {
    if (!options.silent) showError(response.message);
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
      showError(`有 ${progress.failed} 条未采集成功，最后一条错误：${progress.lastError}`);
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
    showError(response.message);
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
    showError(humanizeError(error));
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
  // 「待审核」= 还没表态（review/candidate）；「已入库」只算真正确认过的 verified。
  // 以前用 status !== "review" 统计入库，会把 candidate 也算进去，数字虚高，
  // 看起来像"都进了库"，正好掩盖了审核没做完这件事。
  setText(
    "stat-review",
    String(
      result.items.filter((item) => item.status === "review" || item.status === "candidate")
        .length,
    ),
  );
  setText(
    "stat-created",
    String(result.items.filter((item) => item.status === "verified").length),
  );
  renderKnowledge(result.items);
}

/**
 * 渲染知识点列表，并挂上完整的审核交互。
 *
 * 设计意图：待审核区不是"一键全收"的过场。每条都要能明确表态
 * （确认 / 驳回 / 删除），因为只有被确认的条目才该进 Obsidian；
 * 驳回与删除是审核真正起作用的前提——否则"审核"等价于全部入库。
 */
function renderKnowledge(items: KnowledgeView[]): void {
  state.knowledge = items;
  const list = el<HTMLUListElement>("knowledge-list");
  list.innerHTML = "";

  const pending = items.filter((item) => item.status === "review" || item.status === "candidate");
  // 只有存在待审核条目时才亮出批量栏，避免空列表上摆一排点不动的按钮。
  el("review-bar").hidden = pending.length === 0;
  // 处理过的条目会从待审列表里消失，勾选状态要跟着清掉，否则「已选 N 条」会越积越多。
  const pendingIds = new Set(pending.map((item) => item.id));
  state.selected = new Set([...state.selected].filter((id) => pendingIds.has(id)));
  syncSelectionUi();

  for (const item of items) {
    const li = document.createElement("li");
    li.className = "knowledge-item";

    const isPending = item.status === "review" || item.status === "candidate";
    if (isPending) {
      const pick = document.createElement("input");
      pick.type = "checkbox";
      pick.className = "pick";
      pick.checked = state.selected.has(item.id);
      pick.setAttribute("aria-label", `选择：${item.title}`);
      pick.addEventListener("change", () => {
        if (pick.checked) state.selected.add(item.id);
        else state.selected.delete(item.id);
        syncSelectionUi();
      });
      li.append(pick);
    }

    const body = document.createElement("div");
    body.className = "knowledge-body";
    const title = document.createElement("div");
    title.className = "knowledge-title";
    title.textContent = `${item.title} · ${item.knowledge_type} · ${STATUS_LABEL[item.status] ?? item.status}`;
    const meta = document.createElement("div");
    meta.className = "muted";
    const domain = item.domain ? ` · 域 ${item.domain}` : "";
    meta.textContent = `置信度 ${item.confidence.toFixed(2)} · 来源 ${item.source_message_ids.length} 条 · v${item.version}${domain}`;
    body.append(title, meta);
    if (item.summary) {
      const summary = document.createElement("div");
      summary.className = "muted";
      summary.textContent = item.summary;
      body.append(summary);
    }
    li.append(body);

    const ops = document.createElement("div");
    ops.className = "knowledge-ops";
    if (isPending) {
      ops.append(
        makeOpButton("确认", "primary", () => reviewOne(item.id, "verify")),
        makeOpButton("驳回", "ghost", () => reviewOne(item.id, "reject")),
      );
    } else if (item.status === "rejected") {
      ops.append(makeOpButton("恢复待审", "ghost", () => reviewOne(item.id, "review")));
    }
    // 删除对所有状态开放：噪音条目不该因为"曾经被确认过"就删不掉。
    ops.append(makeOpButton("删除", "ghost danger", () => deleteOne(item)));
    li.append(ops);

    list.append(li);
  }

  updateWriteButtons();
}

function makeOpButton(text: string, className: string, onClick: () => void): HTMLButtonElement {
  const button = document.createElement("button");
  button.className = className;
  button.textContent = text;
  button.addEventListener("click", onClick);
  return button;
}

/** 单条审核。失败只提示，不改动本地状态——以服务端返回为准。 */
async function reviewOne(id: string, action: "verify" | "reject" | "review"): Promise<void> {
  clearError();
  try {
    await state.api.reviewKnowledge(id, action);
    state.selected.delete(id);
    await refreshKnowledge();
  } catch (error) {
    showError(humanizeError(error));
  }
}

/** 删除：二次确认，避免手滑丢掉真正想要的知识。 */
async function deleteOne(item: KnowledgeView): Promise<void> {
  const ok = window.confirm(
    `删除「${item.title}」？\n\n删除后不再出现在列表与 Obsidian 写入范围；误删可用「恢复」找回（后端保留记录）。`,
  );
  if (!ok) return;
  clearError();
  try {
    await state.api.reviewKnowledge(item.id, "delete", "user rejected from sidepanel");
    state.selected.delete(item.id);
    await refreshKnowledge();
  } catch (error) {
    showError(humanizeError(error));
  }
}

/** 批量审核：逐条提交，允许部分失败，最后按服务端结果整体刷新。 */
async function reviewSelected(action: "verify" | "reject" | "delete"): Promise<void> {
  const ids = [...state.selected];
  if (ids.length === 0) {
    setText("review-selected", "请先勾选要处理的条目");
    return;
  }
  if (action === "delete") {
    const ok = window.confirm(`删除选中的 ${ids.length} 条知识？\n\n误删可用「恢复」找回。`);
    if (!ok) return;
  }
  clearError();
  const failed: string[] = [];
  for (const id of ids) {
    try {
      await state.api.reviewKnowledge(id, action, "batch from sidepanel");
    } catch {
      failed.push(id);
    }
  }
  await refreshKnowledge();
  if (failed.length > 0) {
    showError(`${failed.length} 条处理失败，其余已生效。可勾选后重试。`);
  }
}

/** 同步「全选 / 已选 N 条 / 批量按钮可用性」。 */
function syncSelectionUi(): void {
  const pending = state.knowledge.filter(
    (item) => item.status === "review" || item.status === "candidate",
  );
  const count = state.selected.size;
  setText("review-selected", `已选 ${count} 条 / 待审 ${pending.length} 条`);
  const all = el<HTMLInputElement>("chk-select-all");
  all.checked = pending.length > 0 && count === pending.length;
  all.indeterminate = count > 0 && count < pending.length;
  for (const id of ["btn-verify-selected", "btn-reject-selected", "btn-delete-selected"]) {
    el<HTMLButtonElement>(id).disabled = count === 0;
  }
}

/** 写入按钮：区分「全部入库」与「仅确认通过项」，避免审核被绕过。 */
function updateWriteButtons(): void {
  const total = state.lastCompileKnowledgeIds.length;
  const verified = state.knowledge.filter(
    (item) => state.lastCompileKnowledgeIds.includes(item.id) && item.status === "verified",
  ).length;
  const writeAll = el<HTMLButtonElement>("btn-write-current");
  const writeVerified = el<HTMLButtonElement>("btn-write-verified");
  writeAll.textContent = total > 0 ? `写入全部到 Obsidian（${total}）` : "写入全部到 Obsidian";
  writeVerified.textContent = `仅写入已确认（${verified}）`;
  writeVerified.disabled = verified === 0;
  writeVerified.title =
    verified === 0
      ? "还没有已确认的条目：先在上方逐条「确认」，再写入。审核的意义就在于此。"
      : `只写 ${verified} 条已确认的知识，未表态的留在库里不落盘。`;
}

// ------------------------------------------------------------------ 重新分类
/**
 * 重新分类：先预览再执行。
 *
 * 入口说明：此前这个能力只有后端接口（POST /knowledge/reclassify），
 * 没有任何界面能触发，等于失效；现在放在「编译结果」工具栏，
 * 与它要整理的知识点在同一个卡片里。
 */
async function runReclassify(apply: boolean): Promise<void> {
  clearError();
  const preview = el("reclassify-result");
  const applyButton = el<HTMLButtonElement>("btn-reclassify-apply");
  const button = el<HTMLButtonElement>("btn-reclassify");
  button.disabled = true;
  button.textContent = apply ? "应用中…" : "检查中…";
  try {
    const result = await state.api.reclassify({ dry_run: !apply });
    if (result.dry_run) {
      const changes = result.reclassify ?? [];
      const merges = result.merges ?? [];
      if (changes.length === 0 && merges.length === 0) {
        preview.textContent = `已检查 ${result.total ?? 0} 条：主题域与重复情况都没问题，无需调整。`;
        preview.hidden = false;
        applyButton.hidden = true;
        return;
      }
      const lines: string[] = [];
      for (const change of changes.slice(0, 8)) {
        lines.push(`「${change.title}」：${change.from ?? "未分类"} → ${change.to}`);
      }
      if (changes.length > 8) lines.push(`…另有 ${changes.length - 8} 条域调整`);
      for (const merge of merges.slice(0, 8)) {
        lines.push(`合并「${merge.drop_title}」→「${merge.keep_title}」`);
      }
      if (merges.length > 8) lines.push(`…另有 ${merges.length - 8} 组相似合并`);
      preview.textContent = `预览（共 ${result.total ?? 0} 条）：${lines.join("；")}。确认无误再点「应用以上调整」。`;
      preview.hidden = false;
      applyButton.hidden = false;
      return;
    }
    preview.textContent = `已应用：调整 ${result.domain_changes ?? 0} 条主题域，合并 ${result.merges_applied ?? 0} 组。合并可用 unmerge 撤销。`;
    preview.hidden = false;
    applyButton.hidden = true;
    await refreshKnowledge();
  } catch (error) {
    showError(humanizeError(error));
  } finally {
    button.disabled = false;
    button.textContent = "重新分类";
  }
}

async function writeToObsidian(): Promise<void> {
  clearError();
  try {
    const result = await state.api.syncObsidian({ knowledge_ids: state.knowledgeIds });
    setText("sync-status", `已写入 ${result.written.length} 个文件，跳过 ${result.skipped.length} 个（冲突）`);
  } catch (error) {
    showError(humanizeError(error));
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
    showError(`${summary}：${lines.join("；")}`);
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

/**
 * 写入 Obsidian 的公共实现：只写传入的这批 id，失败自动重试 2 次。
 *
 * 两种口径刻意分开暴露成两个按钮：
 * * 写入全部 —— 本次编译产出全部落盘（等于不做筛选）；
 * * 仅写入已确认 —— 只落盘逐条「确认」过的条目，未表态的留在库里。
 * 没有后者，审核就成了摆设。
 */
async function writeIdsToObsidian(ids: string[], buttonId: string): Promise<void> {
  clearError();
  const button = el<HTMLButtonElement>(buttonId);
  if (ids.length === 0) {
    setText("write-target", "没有可写入的条目：先「保存 + 编译」，并至少确认一条。");
    return;
  }
  if (!state.vault?.configured) {
    showError("Obsidian 库未连接：先双击 scripts\\windows\\set-vault.bat 连接一次。");
    return;
  }

  button.disabled = true;
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
    showError(`写入 Obsidian 失败（已重试 2 次）：${humanizeError(lastError)}`);
  } finally {
    button.disabled = false;
    // 文案由 updateWriteButtons 统一维护（含条数），别在这里写死旧文案。
    updateWriteButtons();
  }
}

/** 写入全部：本次编译产出，不看审核状态。 */
function writeCurrentToObsidian(): Promise<void> {
  return writeIdsToObsidian(state.lastCompileKnowledgeIds, "btn-write-current");
}

/** 仅写入已确认：审核真正生效的那条路径。 */
function writeVerifiedToObsidian(): Promise<void> {
  const ids = state.lastCompileKnowledgeIds.filter((id) => {
    const item = state.knowledge.find((entry) => entry.id === id);
    return item?.status === "verified";
  });
  return writeIdsToObsidian(ids, "btn-write-verified");
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
  el("btn-write-verified").addEventListener("click", () => void writeVerifiedToObsidian());

  // 审核：单条按钮在 renderKnowledge 里绑定，这里只管批量栏。
  el<HTMLInputElement>("chk-select-all").addEventListener("change", (event) => {
    const checked = (event.target as HTMLInputElement).checked;
    const pending = state.knowledge.filter(
      (item) => item.status === "review" || item.status === "candidate",
    );
    for (const item of pending) {
      if (checked) state.selected.add(item.id);
      else state.selected.delete(item.id);
    }
    renderKnowledge(state.knowledge);
  });
  el("btn-verify-selected").addEventListener("click", () => void reviewSelected("verify"));
  el("btn-reject-selected").addEventListener("click", () => void reviewSelected("reject"));
  el("btn-delete-selected").addEventListener("click", () => void reviewSelected("delete"));

  el("btn-reclassify").addEventListener("click", () => void runReclassify(false));
  el("btn-reclassify-apply").addEventListener("click", () => void runReclassify(true));
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
    showError(humanizeError(error));
    return;
  }
  // 写入目标提示需要知道库在哪；拿不到也不阻塞面板
  state.vault = await state.api.obsidianStatus().catch(() => null);
  renderWriteTarget();
  await refreshCrawlStatus();
  await refreshKnowledge();
}

void boot();
