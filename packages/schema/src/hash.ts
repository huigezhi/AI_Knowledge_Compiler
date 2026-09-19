/**
 * 内容哈希工具 —— TypeScript 侧实现。
 *
 * 哈希策略（与 `apps/backend/akc/services/hasher.py` 必须逐字节一致）：
 *   1. Unicode NFC 归一化；
 *   2. 换行统一为 \n（CRLF / CR → LF）；
 *   3. 删除零宽字符（U+200B / U+200C / U+200D / U+FEFF）；
 *   4. 每个非空行内，把连续空格与制表符折叠为单个空格；
 *   5. 每行两端去空白；
 *   6. 删除空行，行之间用 \n 连接，整体再 trim。
 *
 * 说明：**哈希不区分“空格数量差异”，但区分换行带来的段落结构**。
 * 这样既能吸收渲染噪声（缩进/对齐），又不会因为段落合并而误判为相同内容。
 */

const ZERO_WIDTH = /[​-‍﻿]/g;

/** 对单段文本做归一化（供哈希使用）。 */
export function normalizeForHash(input: string): string {
  return input
    .normalize("NFC")
    .replace(/\r\n?/g, "\n")
    .replace(ZERO_WIDTH, "")
    .split("\n")
    .map((line) => line.replace(/[ \t]+/g, " ").trim())
    .filter((line) => line.length > 0)
    .join("\n")
    .trim();
}

/** 稳定化的 JSON 序列化：对象键按字典序排列，去掉 undefined。 */
export function canonicalJson(value: unknown): string {
  return JSON.stringify(canonicalize(value));
}

function canonicalize(value: unknown): unknown {
  if (value === null || typeof value !== "object") return value ?? null;
  if (Array.isArray(value)) return value.map(canonicalize);
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(value as Record<string, unknown>).sort()) {
    const v = (value as Record<string, unknown>)[key];
    if (v === undefined) continue;
    out[key] = canonicalize(v);
  }
  return out;
}

/** SHA-256（十六进制）。浏览器与 Node 18+ 均可用 Web Crypto。 */
export async function sha256Hex(input: string): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) {
    throw new Error("Web Crypto unavailable: cannot compute sha256 in this runtime");
  }
  const bytes = new TextEncoder().encode(input);
  const digest = await subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** 带 `sha256:` 前缀的哈希，与数据库中 `content_hash` 列格式一致。 */
export async function contentHash(input: string): Promise<string> {
  return `sha256:${await sha256Hex(normalizeForHash(input))}`;
}
