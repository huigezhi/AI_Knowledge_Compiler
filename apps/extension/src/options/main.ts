/** 设置页：后端地址 / 本地令牌 / 采集策略 / 日志级别。 */

import { AkcApiClient, ApiError, OfflineError } from "@/shared/api-client";
import { ensureHostPermission } from "@/shared/permissions";
import { loadSettings, saveSettings, type ExtensionSettings } from "@/shared/settings";

function el<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`missing element: #${id}`);
  return node as T;
}

function fill(settings: ExtensionSettings): void {
  el<HTMLInputElement>("backend-url").value = settings.backendUrl;
  el<HTMLInputElement>("auth-token").value = settings.authToken;
  el<HTMLInputElement>("batch-size").value = String(settings.batchSize);
  el<HTMLInputElement>("write-raw").checked = settings.writeRawToObsidian;
  el<HTMLInputElement>("auto-compile").checked = settings.autoCompile;
  el<HTMLSelectElement>("log-level").value = settings.logLevel;
}

function collect(): Partial<ExtensionSettings> {
  return {
    backendUrl: el<HTMLInputElement>("backend-url").value.trim() || "http://127.0.0.1:38127",
    authToken: el<HTMLInputElement>("auth-token").value.trim(),
    batchSize: Number(el<HTMLInputElement>("batch-size").value) || 20,
    writeRawToObsidian: el<HTMLInputElement>("write-raw").checked,
    autoCompile: el<HTMLInputElement>("auto-compile").checked,
    logLevel: el<HTMLSelectElement>("log-level").value as ExtensionSettings["logLevel"],
  };
}

function currentClient(): AkcApiClient {
  const patch = collect();
  return new AkcApiClient({
    backendUrl: patch.backendUrl ?? "http://127.0.0.1:38127",
    authToken: patch.authToken ?? "",
  });
}

/** 把状态写进页面（保存/连接/权限结果统一走这里）。 */
function setStatus(text: string, ok = true): void {
  const status = el("status");
  status.textContent = text;
  status.style.color = ok ? "#7ee787" : "#ff8080";
}

/**
 * 远程后端需要动态申请主机权限（MV3 扩展 fetch 受 host_permissions 限制）。
 * 必须在用户手势中调用 —— 所以只绑定在「保存」「测试连接」按钮上。
 */
async function ensureBackendAccess(backendUrl: string): Promise<boolean> {
  const result = await ensureHostPermission(backendUrl);
  if (result.skipped || result.granted) return true;
  setStatus(
    `未授权访问 ${result.origin}，扩展无法把数据发到该地址；请重新点击保存并在弹窗中选择「允许」`,
    false,
  );
  return false;
}

async function saveAll(): Promise<void> {
  const patch = collect();
  if (!(await ensureBackendAccess(patch.backendUrl ?? ""))) return;
  await saveSettings(patch);
  setStatus("设置已保存");
}

async function testConnection(): Promise<void> {
  setStatus("正在连接…");
  const patch = collect();
  if (!(await ensureBackendAccess(patch.backendUrl ?? ""))) return;
  try {
    const health = await currentClient().health();
    setStatus(`已连接：v${health.version} · schema ${health.schema_version}`);
  } catch (error) {
    const message =
      error instanceof ApiError
        ? error.userMessage
        : error instanceof OfflineError
          ? error.message
          : `连接失败：${String(error)}`;
    setStatus(message, false);
  }
}

async function boot(): Promise<void> {
  fill(await loadSettings());
  el("btn-test").addEventListener("click", () => void testConnection());
  el("btn-save").addEventListener("click", () => void saveAll());
}

void boot();
