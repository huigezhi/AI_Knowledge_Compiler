#!/usr/bin/env node
/**
 * 在**真实的已登录浏览器**里运行 DOM 结构探针。
 *
 * 解决的核心问题：平台页面需要登录，开发者拿不到真实 DOM，只能盲猜选择器。
 *
 * 两种接入方式（二选一）：
 *
 * A. 连接你已经用调试端口启动的 Chrome（推荐，不复制任何数据）
 *      chrome.exe --remote-debugging-port=9222
 *      node probe-real-page.mjs --cdp http://127.0.0.1:9222 --url https://www.doubao.com/chat/xxx
 *
 * B. 用你 Chrome 登录数据的**副本**启动独立实例（不用关闭正在用的 Chrome）
 *      node probe-real-page.mjs --clone-profile --url https://www.doubao.com/chat/xxx
 *      副本写在系统临时目录，进程退出即删除；只复制 Cookies / Local Storage / Local State。
 *
 * 输出：脱敏结构报告（文本全部替换为 {n字}，不含任何对话内容），可直接贴给维护者。
 */

import { createRequire } from "node:module";
import { cpSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const PW_ROOT = process.env.AKC_PW || "E:/workbuddy_files/.tools/node_modules/playwright-core";
const CHROME_DEFAULT =
  process.env.AKC_CHROME ||
  join(
    process.env.LOCALAPPDATA || "",
    "ms-playwright",
    "chromium-1179",
    "chrome-win",
    "chrome.exe",
  );
const CHROME_USER_DATA =
  process.env.AKC_CHROME_USER_DATA ||
  join(process.env.LOCALAPPDATA || "", "Google", "Chrome", "User Data");

const here = dirname(fileURLToPath(import.meta.url));
const PROBE = readFileSync(resolve(here, "dom-probe.js"), "utf8");

function parseArgs(argv) {
  const opts = { urls: [], wait: 6000, screenshot: false, cloneProfile: false, headless: false };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === "--url") opts.urls.push(argv[++i]);
    else if (a === "--cdp") opts.cdp = argv[++i];
    else if (a === "--chrome") opts.chrome = argv[++i];
    else if (a === "--user-data-dir") opts.userDataDir = argv[++i];
    else if (a === "--clone-profile") opts.cloneProfile = true;
    else if (a === "--wait") opts.wait = Number(argv[++i]);
    else if (a === "--screenshot") opts.screenshot = true;
    else if (a === "--send") opts.send = argv[++i];
    else if (a === "--out") opts.out = argv[++i];
    else if (a === "--headless") opts.headless = true;
    else if (a === "-h" || a === "--help") opts.help = true;
  }
  return opts;
}

/** 只复制登录态必需的最小文件集，避免整份 profile（几百 MB）。 */
function cloneProfile() {
  const src = CHROME_USER_DATA;
  if (!existsSync(src)) throw new Error(`找不到 Chrome 配置目录：${src}`);
  const dst = mkdtempSync(join(tmpdir(), "akc-chrome-"));
  const items = [
    ["Local State", "Local State"],
    [join("Default", "Cookies"), join("Default", "Cookies")],
    [join("Default", "Preferences"), join("Default", "Preferences")],
    [join("Default", "Local Storage"), join("Default", "Local Storage")],
    [join("Default", "Network", "Cookies"), join("Default", "Network", "Cookies")],
  ];
  const copied = [];
  const failed = [];
  for (const [from, to] of items) {
    const s = join(src, from);
    if (!existsSync(s)) continue;
    const target = join(dst, to);
    try {
      cpSync(s, target, { recursive: true });
      copied.push(from);
    } catch {
      // Chrome 运行时会对 SQLite 加排他锁（EBUSY）；退回逐字节读取，
      // SQLite 一般允许共享读，失败则记下来提示用户关闭 Chrome。
      try {
        writeFileSync(target, readFileSync(s));
        copied.push(from);
      } catch {
        failed.push(from);
      }
    }
  }
  if (copied.length === 0) throw new Error("没有复制到任何登录数据，请检查 Chrome 是否安装过");
  if (failed.length > 0) {
    console.log(`[probe] 以下文件被 Chrome 锁定、复制失败：${failed.join(", ")}`);
    console.log("[probe] 若登录态无效，请先完全退出 Chrome 再重试");
  }
  console.log(`[probe] 已复制登录数据到临时副本：${copied.join(", ")}`);
  return dst;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help || opts.urls.length === 0) {
    console.log(readFileSync(fileURLToPath(import.meta.url), "utf8").split("*/")[0]);
    return 2;
  }

  const { chromium } = require(PW_ROOT);
  let browser;
  let context;
  let tempProfile = null;

  if (opts.cdp) {
    console.log(`[probe] 连接到已运行的 Chrome：${opts.cdp}`);
    browser = await chromium.connectOverCDP(opts.cdp);
    context = browser.contexts()[0] ?? (await browser.newContext());
  } else {
    const userDataDir = opts.userDataDir ?? (opts.cloneProfile ? (tempProfile = cloneProfile()) : undefined);
    console.log(`[probe] 启动独立 Chromium：${opts.chrome ?? CHROME_DEFAULT}`);
    context = await chromium.launchPersistentContext(userDataDir ?? "", {
      executablePath: opts.chrome ?? CHROME_DEFAULT,
      headless: opts.headless,
      viewport: { width: 1440, height: 900 },
      args: ["--no-first-run", "--no-default-browser-check", "--disable-blink-features=AutomationControlled"],
    });
  }

  const reports = [];
  try {
    for (const url of opts.urls) {
      const page = await context.newPage();
      console.log(`[probe] 打开 ${url}`);
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 }).catch((e) => {
        console.log(`[probe] 导航告警：${e.message}`);
      });
      if (opts.send) {
        // 空会话页看不到消息容器结构；主动发一条消息把真实结构"逼"出来。
        // 各平台的输入框差异很大，这里按「可见的 contenteditable / textarea」逐个试。
        // SPA 首帧还没有输入框，必须先等它渲染出来（之前直接 count() 得到 0 就跳过了）
        await page
          .waitForSelector(".tiptap.ProseMirror, p[data-placeholder], [contenteditable='true'], textarea", {
            timeout: 30000,
          })
          .catch(() => console.log("[probe] 等待输入框超时，仍尝试候选定位"));

        const candidates = [
          ".tiptap.ProseMirror", // 豆包：tiptap / ProseMirror 富文本编辑器
          "p[data-placeholder]",
          ".ProseMirror",
          "#input-engine-container [contenteditable='true']",
          "[contenteditable='true'][role='textbox']",
          "textarea",
          "div[contenteditable='true']",
        ];
        let typed = false;
        for (const sel of candidates) {
          const loc = page.locator(sel).first();
          try {
            if ((await loc.count()) === 0) continue;
            await loc.waitFor({ state: "visible", timeout: 8000 });
            await loc.click({ timeout: 5000 });
            // 富文本编辑器（tiptap / ProseMirror）不响应 fill，必须走真实按键序列
            await loc.pressSequentially(opts.send, { delay: 100 });
            const entered = (await loc.textContent())?.trim() ?? "";
            if (!entered) {
              console.log(`[probe] ${sel} 未接受输入，试下一个`);
              continue;
            }
            await page.keyboard.press("Enter");
            typed = true;
            console.log(`[probe] 已通过 ${sel} 输入「${entered.slice(0, 20)}」并回车`);
            break;
          } catch (e) {
            console.log(`[probe] 尝试 ${sel} 失败：${e.message.split("\n")[0]}`);
          }
        }
        if (!typed) console.log("[probe] 未找到可用输入框，跳过发送");
        await page.waitForTimeout(opts.wait);
        console.log("[probe] 等待渲染完成");
      }
      await page.waitForTimeout(opts.wait); // 等 SPA 把消息渲染出来
      const report = await page.evaluate(PROBE);
      report.requested_url = url;
      reports.push(report);

      console.log(
        `[probe] 命中：message-item=${report.currentSelectors["[data-testid='message-item'], .message-item"]} ` +
          `data-role=${report.currentSelectors["[data-role]"]} ` +
          `iframe=${report.counts.iframes} shadowHost=${report.counts.shadowHosts}`,
      );
      console.log(`[probe] 疑似消息容器样本：${report.messageSamples.length} 个`);
      if (opts.screenshot) {
        const file = `probe-${Date.now()}.png`;
        await page.screenshot({ path: file, fullPage: false });
        console.log(`[probe] 截图：${file}`);
      }
      await page.close();
    }
  } finally {
    if (opts.cdp) await browser.close().catch(() => {});
    else await context.close().catch(() => {});
    if (tempProfile) rmSync(tempProfile, { recursive: true, force: true });
  }

  const json = JSON.stringify(reports, null, 2);
  if (opts.out) {
    writeFileSync(opts.out, json, "utf8");
    console.log(`[probe] 报告已写入 ${opts.out}`);
  }
  console.log(json);
  return 0;
}

main().then(
  (code) => process.exit(code),
  (error) => {
    console.error(`[probe] 失败：${error.message}`);
    process.exit(1);
  },
);
