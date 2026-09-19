/**
 * 远程后端的主机权限申请。
 *
 * 背景：MV3 扩展页面的跨域 fetch 必须在 host_permissions / optional_host_permissions 内，
 * 否则会被 Chrome 拦截。默认只声明本地回环地址，远程后端（VPS）需要动态申请。
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { ensureHostPermission, originPattern } from "../permissions";

interface FakePermissionApi {
  contains: ReturnType<typeof vi.fn>;
  request: ReturnType<typeof vi.fn>;
}

function stubChrome(api: Partial<FakePermissionApi> | null): FakePermissionApi | null {
  if (api === null) {
    vi.unstubAllGlobals();
    return null;
  }
  const full: FakePermissionApi = {
    contains: api.contains ?? vi.fn(),
    request: api.request ?? vi.fn(),
  };
  vi.stubGlobal("chrome", { permissions: full });
  return full;
}

describe("originPattern", () => {
  it("把地址转换为权限匹配模式", () => {
    expect(originPattern("http://127.0.0.1:38127")).toBe("http://127.0.0.1:38127/*");
    expect(originPattern("https://akc.example.com")).toBe("https://akc.example.com/*");
    expect(originPattern("https://akc.example.com:8443/api/v1")).toBe("https://akc.example.com:8443/*");
  });

  it("非法或空地址返回空串", () => {
    expect(originPattern("")).toBe("");
    expect(originPattern("   ")).toBe("");
    expect(originPattern("not-a-url")).toBe("");
  });
});

describe("ensureHostPermission", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("非扩展环境跳过申请（不阻塞保存）", async () => {
    stubChrome(null);
    const result = await ensureHostPermission("https://akc.example.com");
    expect(result.skipped).toBe(true);
    expect(result.granted).toBe(true);
  });

  it("本地地址已有静态权限时不发起申请", async () => {
    const api = stubChrome({ contains: vi.fn((_p, cb: (v: boolean) => void) => cb(true)) })!;
    const result = await ensureHostPermission("http://127.0.0.1:38127");
    expect(result.granted).toBe(true);
    expect(api.request).not.toHaveBeenCalled();
  });

  it("远程地址缺少权限时发起申请并返回结果", async () => {
    const api = stubChrome({
      contains: vi.fn((_p, cb: (v: boolean) => void) => cb(false)),
      request: vi.fn((_p, cb: (v: boolean) => void) => cb(true)),
    })!;
    const result = await ensureHostPermission("https://akc.example.com");
    expect(result.granted).toBe(true);
    expect(result.origin).toBe("https://akc.example.com/*");
    expect(api.request).toHaveBeenCalledWith(
      { origins: ["https://akc.example.com/*"] },
      expect.any(Function),
    );
  });

  it("用户拒绝授权时返回 false（调用方需提示）", async () => {
    stubChrome({
      contains: vi.fn((_p, cb: (v: boolean) => void) => cb(false)),
      request: vi.fn((_p, cb: (v: boolean) => void) => cb(false)),
    });
    const result = await ensureHostPermission("https://akc.example.com");
    expect(result.granted).toBe(false);
    expect(result.skipped).toBe(false);
  });

  it("申请抛错（非用户手势）时按未授权处理", async () => {
    stubChrome({
      contains: vi.fn((_p, cb: (v: boolean) => void) => cb(false)),
      request: vi.fn(() => {
        throw new Error("This function must be called during a user gesture");
      }),
    });
    const result = await ensureHostPermission("https://akc.example.com");
    expect(result.granted).toBe(false);
  });

  it("地址非法时跳过申请", async () => {
    const api = stubChrome({ contains: vi.fn(), request: vi.fn() })!;
    const result = await ensureHostPermission("not-a-url");
    expect(result.skipped).toBe(true);
    expect(api.contains).not.toHaveBeenCalled();
  });
});
