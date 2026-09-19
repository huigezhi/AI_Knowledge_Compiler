#!/usr/bin/env node
/**
 * 线上端到端验证：把**生产适配器代码**打包后注入真实已登录页面执行。
 *
 * 与 fixtures 单测的分工：
 *   - fixtures 单测保证「逻辑没退化」（快、离线、但结构是模拟的）
 *   - 本脚本保证「选择器在真实页面上确实有效」（慢、需登录态、但是真相）
 *
 * 前置：Chrome 以调试端口启动（scripts/windows/start-chrome-debug.bat），
 *       并在该窗口里登录目标平台。
 *
 * 用法：
 *   node scripts/verify-live.mjs --provider doubao --url https://www.doubao.com/chat/<id>
 *   node scripts/verify-live.mjs --provider doubao --url <conv> --cdp http://127.0.0.1:9222
 *
 * 输出：健康检查、对话标题、消息数与角色序列、内容块类型、历史列表标题。
 * 注意：只在页面内做判断，回传的是长度/摘要而非整段对话内容。
 */


import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const PW_ROOT = process.env.AKC_PW || "E:/workbuddy_files/.tools/node_modules/playwright-core";
const EXT_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function parseArgs(argv) {
  const opts = { cdp: "http://127.0.0.1:9222", wait: 5000, preview: 30 };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === "--provider") opts.provider = argv[++i];
    else if (a === "--url") opts.url = argv[++i];
    else if (a === "--cdp") opts.cdp = argv[++i];
    else if (a === "--wait") opts.wait = Number(argv[++i]);
    else if (a === "-h" || a === "--help") opts.help = true;
  }
  return opts;
}

/** 用 esbuild 把生产适配器打成可注入的 IIFE（避免另写一份"复刻逻辑"）。 */
function buildBundle(provider) {
  const req = createRequire(join(EXT_DIR, "package.json"));
  const esbuild = req("esbuild");
  const dir = mkdtempSync(join(tmpdir(), "akc-verify-"));
  const entry = join(dir, "entry.ts");
  const out = join(dir, "bundle.js");
  writeFileSync(
    entry,
    `import { adapterById } from "${EXT_DIR.replace(/\\/g, "/")}/src/adapters/registry";\n` +
      `(globalThis as any).__AKC_LIVE__ = { adapter: adapterById(${JSON.stringify(provider)} as never) };\n`,
    "utf8",
  );
  esbuild.buildSync({
    entryPoints: [entry],
    bundle: true,
    format: "iife",
    target: "chrome116",
    outfile: out,
    alias: { "@akc/schema": resolve(EXT_DIR, "../../packages/schema/src") },
    logLevel: "warning",
  });
  return { dir, code: readFileSync(out, "utf8") };
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help || !opts.provider || !opts.url) {
    console.log(readFileSync(fileURLToPath(import.meta.url), "utf8").split("*/")[0]);
    return 2;
  }

  const { chromium } = require(PW_ROOT);
  const built = buildBundle(opts.provider);
  const browser = await chromium.connectOverCDP(opts.cdp);
  const context = browser.contexts()[0];
  const page = await context.newPage();

  try {
    await page.goto(opts.url, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(opts.wait);
    await page.addScriptTag({ content: built.code });

    const report = await page.evaluate(async () => {
      const adapter = globalThis.__AKC_LIVE__?.adapter;
      if (!adapter) return { error: "bundle 未加载" };
      const out = { provider: adapter.id, adapterVersion: adapter.adapterVersion };
      try {
        const health = await adapter.healthCheck();
        out.health = { status: health.status, domVersion: health.dom_version, message: health.message };
        out.page = adapter.detectPage();

        const conv = await adapter.fetchCurrentConversation();
        out.conversation = {
          title: conv.title,
          providerConversationId: conv.provider_conversation_id,
          messageCount: conv.messages.length,
          roles: conv.messages.map((m) => m.role),
          sequences: conv.messages.map((m) => m.sequence),
          hashesValid: conv.messages.every((m) => /^sha256:[0-9a-f]{64}$/.test(m.content_hash)),
          blockTypes: conv.messages.map((m) => m.content.map((b) => b.type).join("+")),
          previews: conv.messages.slice(0, 4).map((m) => {
            const text = m.content.map((b) => b.text || "").join("\n");
            return { role: m.role, len: text.length, head: text.slice(0, 40) };
          }),
        };
        const items = await adapter.listConversations({ limit: 5 });
        out.history = { count: items.length, titles: items.map((i) => i.title) };
      } catch (e) {
        out.error = e?.message ?? String(e);
      }
      return out;
    });

    console.log(JSON.stringify(report, null, 2));
    if (report.error) return 1;
    // 基本断言：健康、有消息、角色序列以 user 开头
    const ok =
      report.health?.status === "healthy" &&
      (report.conversation?.messageCount ?? 0) > 0 &&
      report.conversation?.hashesValid === true &&
      report.conversation?.roles?.[0] === "user";
    console.log(ok ? "\n[verify] PASS" : "\n[verify] FAIL —— 选择器可能已失效，见 docs/adapters.md §8");
    return ok ? 0 : 1;
  } finally {
    await page.close().catch(() => {});
    rmSync(built.dir, { recursive: true, force: true });
  }
}

main().then(
  (code) => process.exit(code),
  (error) => {
    console.error(`[verify] 失败：${error.message}`);
    process.exit(1);
  },
);
