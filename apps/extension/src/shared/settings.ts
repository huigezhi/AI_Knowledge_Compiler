/**
 * 扩展本地设置。
 *
 * 安全约定：
 * * Claude API Key **不保存在扩展 storage**——它由后端从环境变量读取；
 *   扩展只保存后端地址与本地访问令牌，避免密钥散落在浏览器里。
 * * 所有设置项都有默认值，缺失时不会阻塞 UI。
 */

export interface ExtensionSettings {
  backendUrl: string;
  authToken: string;
  /** 是否“保存后自动进入编译队列” */
  autoCompile: boolean;
  /** 保存时是否同时把 Raw 写入 Obsidian */
  writeRawToObsidian: boolean;
  /** 批量同步时的并发上限（队列串行，这里限制单次提交数量） */
  batchSize: number;
  /**
   * 自动保存当前会话：页面内容变化后静默一段时间即自动入库，无需点按钮。
   * 数据只发往本机后端，不经过任何第三方。
   */
  autoSave: boolean;
  /** 自动保存的去抖时长（秒）：连续输入期间不打断，停手这么久后才保存。 */
  autoSaveDelaySeconds: number;
  /**
   * 历史会话后台静默同步：不跳转页面、不打开侧边栏，由 Service Worker
   * 定期（chrome.alarms）让平台页的内容脚本同域抓取会话页并解析入库。
   */
  historyAutoSync: boolean;
  /** 历史静默同步的周期（分钟）。 */
  historySyncIntervalMinutes: number;
  /** 自动遍历历史会话时，跳过后端已存在的会话（只补没采过的）。 */
  crawlSkipExisting: boolean;
  /** 单个历史会话的最长等待时间（秒），超时就跳过，避免卡死。 */
  crawlItemTimeoutSeconds: number;
  /** 日志级别 */
  logLevel: "debug" | "info" | "warn" | "error";
}

export const DEFAULT_SETTINGS: ExtensionSettings = {
  backendUrl: "http://127.0.0.1:38127",
  authToken: "",
  // 全自动链路的默认值：采集即编译，用户零操作
  autoCompile: true,
  writeRawToObsidian: true,
  batchSize: 20,
  autoSave: true,
  // 5 秒：比 15 秒更跟手，又不会在流式输出期间频繁打断
  autoSaveDelaySeconds: 5,
  historyAutoSync: true,
  historySyncIntervalMinutes: 15,
  crawlSkipExisting: true,
  crawlItemTimeoutSeconds: 20,
  logLevel: "info",
};

const STORAGE_KEY = "akc.settings";

/** ``chrome.storage`` 在测试/非扩展环境下不存在，这里统一降级到内存，保证 UI 可渲染。 */
const memory = new Map<string, unknown>();

function getStorage(): chrome.storage.LocalStorageArea | null {
  return globalThis.chrome?.storage?.local ?? null;
}

async function storageGet<T>(key: string): Promise<T | undefined> {
  const storage = getStorage();
  if (!storage) return memory.get(key) as T | undefined;
  return new Promise((resolve) => {
    storage.get(key, (items) => resolve(items?.[key] as T | undefined));
  });
}

async function storageSet(key: string, value: unknown): Promise<void> {
  const storage = getStorage();
  if (!storage) {
    memory.set(key, value);
    return;
  }
  await new Promise<void>((resolve) => storage.set({ [key]: value }, () => resolve()));
}

export async function loadSettings(): Promise<ExtensionSettings> {
  const stored = { ...((await storageGet<Partial<ExtensionSettings>>(STORAGE_KEY)) ?? {}) };
  // 迁移：旧版默认 15 秒是"没改过"的标记，统一升到新的 5 秒默认值；
  // 用户显式改过的其它值不受影响。
  if (stored.autoSaveDelaySeconds === 15) delete stored.autoSaveDelaySeconds;
  if (stored.autoCompile === false) delete stored.autoCompile;
  return { ...DEFAULT_SETTINGS, ...stored } as ExtensionSettings;
}

export async function saveSettings(patch: Partial<ExtensionSettings>): Promise<ExtensionSettings> {
  const next = { ...(await loadSettings()), ...patch };
  await storageSet(STORAGE_KEY, next);
  return next;
}
