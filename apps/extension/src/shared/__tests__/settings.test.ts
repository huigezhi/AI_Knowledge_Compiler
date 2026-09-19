import { describe, expect, it } from "vitest";
import {
  AUTO_SAVE_PRESET_SECONDS,
  DEFAULT_SETTINGS,
  resolveAutoSaveDelaySeconds,
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
