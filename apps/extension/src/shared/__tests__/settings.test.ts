import { beforeEach, describe, expect, it } from "vitest";
import {
  AUTO_SAVE_PRESET_SECONDS,
  DEFAULT_SETTINGS,
  loadSettings,
  resolveAutoSaveDelaySeconds,
  saveSettings,
  shouldCompile,
  type ExtensionSettings,
} from "@/shared/settings";

function withPreset(preset: ExtensionSettings["autoSaveDelayPreset"], seconds: number): ExtensionSettings {
  return { ...DEFAULT_SETTINGS, autoSaveDelayPreset: preset, autoSaveDelaySeconds: seconds };
}

describe("自动保存间隔档位", () => {
  it("预设档位折算成对应秒数", () => {
    expect(resolveAutoSaveDelaySeconds(withPreset("5s", 5))).toBe(5);
    expect(resolveAutoSaveDelaySeconds(withPreset("2m", 5))).toBe(120);
    expect(resolveAutoSaveDelaySeconds(withPreset("5m", 5))).toBe(300);
    expect(AUTO_SAVE_PRESET_SECONDS["2m"]).toBe(120);
  });

  it("自定义档位用填入的秒数；非法值回落到默认 5 秒", () => {
    expect(resolveAutoSaveDelaySeconds(withPreset("custom", 45))).toBe(45);
    // 0 会让 AI 流式输出的每一帧都触发采集，必须被夹住（回落到默认档）
    expect(resolveAutoSaveDelaySeconds(withPreset("custom", 0))).toBe(5);
  });

  it("默认档位是 5 秒，历史同步默认 10 分钟", () => {
    expect(DEFAULT_SETTINGS.autoSaveDelayPreset).toBe("5s");
    expect(resolveAutoSaveDelaySeconds(DEFAULT_SETTINGS)).toBe(5);
    expect(DEFAULT_SETTINGS.historySyncIntervalMinutes).toBe(10);
  });
});

describe("是否开启 AI 编译", () => {
  const base = DEFAULT_SETTINGS;

  it("总开关关闭时，任何情况都不编译", () => {
    expect(shouldCompile({ ...base, aiCompileEnabled: false, autoCompile: true })).toBe(false);
    expect(shouldCompile({ ...base, aiCompileEnabled: false, autoCompile: false })).toBe(false);
  });

  it("总开关开启时，由「自动编译」决定是否编", () => {
    expect(shouldCompile({ ...base, aiCompileEnabled: true, autoCompile: true })).toBe(true);
    expect(shouldCompile({ ...base, aiCompileEnabled: true, autoCompile: false })).toBe(false);
  });

  it("默认开启编译", () => {
    expect(base.aiCompileEnabled).toBe(true);
    expect(shouldCompile(base)).toBe(true);
  });
});

describe("设置持久化", () => {
  beforeEach(async () => {
    // 还原成默认，避免用例之间互相污染（storage 在测试环境下走内存兜底）
    await saveSettings({ ...DEFAULT_SETTINGS });
  });

  it("取消勾选「自动编译」后能被保存住，不会一刷新又变回勾选", async () => {
    // 回归：loadSettings 里曾经无条件删除 autoCompile===false，
    // 导致这个开关永远关不掉。
    await saveSettings({ aiCompileEnabled: true, autoCompile: false });
    const loaded = await loadSettings();
    expect(loaded.autoCompile).toBe(false);
    expect(shouldCompile(loaded)).toBe(false);
  });

  it("总开关关闭后能被持久化", async () => {
    await saveSettings({ aiCompileEnabled: false });
    const loaded = await loadSettings();
    expect(loaded.aiCompileEnabled).toBe(false);
    expect(shouldCompile(loaded)).toBe(false);
  });
});
