/**
 * API 客户端边界行为测试。
 *
 * 覆盖前端边界规则：
 * * 4xx → 映射为可读文案且不重试；
 * * 5xx → 指数退避重试（最多 3 次）后仍失败则抛出；
 * * 网络失败 → ``OfflineError``（UI 显示离线提示）；
 * * 写请求自动附带 ``X-AKC-Token``。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AkcApiClient, ApiError, humanizeBackendCode, OfflineError } from "../api-client";

const fetchMock = vi.fn();

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

describe("AkcApiClient", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  const client = () => new AkcApiClient({ backendUrl: "http://127.0.0.1:38127/", authToken: "t-1" });

  it("4xx 不重试，并映射为可读文案", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(422, {
        error: { code: "SCHEMA_VALIDATION_FAILED", message: "bad payload", retryable: false },
        request_id: "r-1",
      }),
    );
    const promise = client().health();
    await expect(promise).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    try {
      await client().health();
    } catch (error) {
      expect((error as ApiError).userMessage).toContain("不符合数据规范");
      expect((error as ApiError).requestId).toBe("r-1");
    }
  });

  it("5xx 重试 3 次后抛出", async () => {
    fetchMock.mockResolvedValue(jsonResponse(500, { error: { code: "INTERNAL", message: "boom", retryable: true } }));
    const promise = client().health();
    // 让退避定时器立即推进
    const assertion = expect(promise).rejects.toBeInstanceOf(ApiError);
    await vi.runAllTimersAsync();
    await assertion;
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("网络失败抛出 OfflineError", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const promise = client().health();
    const assertion = expect(promise).rejects.toBeInstanceOf(OfflineError);
    await vi.runAllTimersAsync();
    await assertion;
  });

  it("写请求附带 X-AKC-Token", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { id: "job_1", status: "pending" }));
    await client().createCompileJob("conv_1");
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)["X-AKC-Token"]).toBe("t-1");
    expect(JSON.parse(String(init.body))).toEqual({ conversation_id: "conv_1" });
  });

  it("后端地址末尾斜杠被正确处理", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { status: "ok" }));
    await client().health();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://127.0.0.1:38127/api/v1/health");
  });
});

/**
 * 错误码翻译必须能覆盖**异步任务失败**这条路径。
 *
 * 曾经只挂在 HTTP 错误响应上，于是 GET /jobs 返回的 error（后端英文原文）
 * 被直接甩给用户 —— 本用例锁住这个回归。
 */
describe("humanizeBackendCode", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("LLM 未启用时给出可执行指引，而不是后端英文原文", () => {
    const text = humanizeBackendCode("LLM_DISABLED");
    expect(text).toBeTruthy();
    expect(text).toContain("set-llm.bat");
    expect(text).not.toContain("AKC_LLM_ENABLED");
  });

  it("未知错误码返回 null，交由调用方回落到原始 message", () => {
    expect(humanizeBackendCode("SOMETHING_ELSE")).toBeNull();
    expect(humanizeBackendCode(null)).toBeNull();
    expect(humanizeBackendCode(undefined)).toBeNull();
  });

  it("HTTP 错误响应也走同一份翻译", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(400, { error: { code: "LLM_DISABLED", message: "llm compiler is disabled", retryable: false } }),
    );
    const apiClient = new AkcApiClient({ backendUrl: "http://127.0.0.1:38127", authToken: "" });
    try {
      await apiClient.createCompileJob("conv_1");
      expect.unreachable("应当抛错");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).userMessage).toContain("set-llm.bat");
    }
  });
});
