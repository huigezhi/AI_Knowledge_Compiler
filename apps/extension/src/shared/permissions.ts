/**
 * 后端地址的主机权限申请。
 *
 * MV3 扩展页面发起的跨域 fetch 必须落在 ``host_permissions`` 或
 * ``optional_host_permissions`` 内，否则会被 Chrome 直接拦截。
 * 默认只声明本地回环地址；当用户在设置里填了远程后端（例如 VPS 域名）时，
 * 由这里在「保存」这一用户手势中动态申请对应 origin 的权限。
 */

export interface HostPermissionResult {
  /** 是否已具备访问权限（跳过申请也算具备）。 */
  granted: boolean;
  /** 申请/检查的 origin 模式，形如 ``https://akc.example.com/*``。 */
  origin: string;
  /** 非扩展环境（测试、普通网页）或地址非法时为 true，表示未做任何申请。 */
  skipped: boolean;
}

/** 把后端地址转换为权限匹配模式；地址非法时返回空串。 */
export function originPattern(backendUrl: string): string {
  const trimmed = (backendUrl ?? "").trim();
  if (!trimmed) return "";
  try {
    return `${new URL(trimmed).origin}/*`;
  } catch {
    return "";
  }
}

function permissionsApi(): typeof chrome.permissions | null {
  return globalThis.chrome?.permissions ?? null;
}

function contains(api: typeof chrome.permissions, origins: string[]): Promise<boolean> {
  return new Promise((resolve) => {
    try {
      api.contains({ origins }, (result) => resolve(Boolean(result)));
    } catch {
      resolve(false);
    }
  });
}

function request(api: typeof chrome.permissions, origins: string[]): Promise<boolean> {
  return new Promise((resolve) => {
    try {
      api.request({ origins }, (granted) => resolve(Boolean(granted)));
    } catch {
      // 非用户手势等情况下会抛错，按未授权处理
      resolve(false);
    }
  });
}

/**
 * 确保扩展有权访问给定的后端地址。
 *
 * 注意：``chrome.permissions.request`` 只能在用户手势中调用，
 * 因此必须绑定在「保存设置」这类点击事件里，不能在页面加载时调用。
 */
export async function ensureHostPermission(backendUrl: string): Promise<HostPermissionResult> {
  const origin = originPattern(backendUrl);
  const api = permissionsApi();
  if (!api || !origin) {
    return { granted: true, origin, skipped: true };
  }
  if (await contains(api, [origin])) {
    return { granted: true, origin, skipped: false };
  }
  const granted = await request(api, [origin]);
  return { granted, origin, skipped: false };
}
