/** 设置页：后端地址 / 本地令牌 / 采集策略 / 日志级别。 */

import { AkcApiClient, ApiError, OfflineError } from "@/shared/api-client";
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

async function testConnection(): Promise<void> {
  const status = el("status");
  status.textContent = "正在连接…";
  try {
    const health = await currentClient().health();
    status.textContent = `已连接：v${health.version} · schema ${health.schema_version}`;
    status.style.color = "#7ee787";
  } catch (error) {
    status.textContent =
      error instanceof ApiError
        ? error.userMessage
        : error instanceof OfflineError
          ? error.message
          : `连接失败：${String(error)}`;
    status.style.color = "#ff8080";
  }
}

async function boot(): Promise<void> {
  fill(await loadSettings());
  el("btn-test").addEventListener("click", () => void testConnection());
  el("btn-save").addEventListener("click", () => {
    void saveSettings(collect()).then(() => {
      const status = el("status");
      status.textContent = "设置已保存";
      status.style.color = "#7ee787";
    });
  });
}

void boot();
