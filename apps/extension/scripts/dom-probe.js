/**
 * AKC DOM 结构探针 —— 平台页面结构变化时，用它把真实结构回传给开发者。
 *
 * 用法：
 *   1. 在目标平台的对话页面按 F12 打开开发者工具，切到 Console
 *   2. 整段复制本文件内容，粘贴到 Console 回车
 *   3. 复制输出的 JSON（已脱敏）发给维护者
 *
 * 隐私：**不输出任何对话文字**——所有文本都被替换成 ``{n字}`` 占位符，
 * 只保留标签名、class、data-* 属性与嵌套结构。
 */
(() => {
  const MAX_DEPTH = 6;
  const PLACEHOLDER = (s) => `{${s.trim().length}字}`;
  const interesting = /(message|msg|chat|bubble|markdown|content|answer|reply|question|role|turn|dialog)/i;

  const describe = (el, depth = 0, includeText = false) => {
    if (depth > MAX_DEPTH) return `${el.tagName.toLowerCase()}…`;
    const attrs = [];
    for (const a of el.attributes) {
      if (a.name === "class") {
        const cls = a.value.trim().replace(/\s+/g, ".").slice(0, 120);
        attrs.push(`class="${cls}"`);
      } else if (
        a.name.startsWith("data-") ||
        a.name === "role" ||
        a.name === "aria-label" ||
        a.name === "id"
      ) {
        attrs.push(`${a.name}="${a.value.slice(0, 60)}"`);
      }
    }
    const own = Array.from(el.childNodes)
      .filter((n) => n.nodeType === 3 && n.textContent.trim())
      .reduce((sum, n) => sum + n.textContent.trim().length, 0);
    const tag = el.tagName.toLowerCase();
    const head = `<${tag}${attrs.length ? " " + attrs.join(" ") : ""}>`;
    const text = own > 0 ? (includeText ? PLACEHOLDER(el.textContent) : `${own}字`) : "";
    const kids = Array.from(el.children)
      .slice(0, 8)
      .map((c) => describe(c, depth + 1, includeText));
    const more = el.children.length > 8 ? [`…还有${el.children.length - 8}个子节点`] : [];
    const inner = [...kids, ...more].filter(Boolean);
    return inner.length ? `${head}${text ? " " + text : ""} [${inner.join(", ")}]` : `${head}${text ? " " + text : ""}`;
  };

  /* ---- 1. 属性统计：哪些 data-* 真正被用来标记消息 ---- */
  const attrStat = {};
  const classStat = {};
  document.querySelectorAll("*").forEach((el) => {
    for (const a of el.attributes) {
      if (a.name.startsWith("data-")) {
        const k = `${a.name}="${a.value.slice(0, 40)}"`;
        attrStat[k] = (attrStat[k] || 0) + 1;
      } else if (a.name === "class" && interesting.test(a.value)) {
        for (const c of a.value.split(/\s+/)) {
          if (interesting.test(c)) classStat[c] = (classStat[c] || 0) + 1;
        }
      }
    }
  });
  const topByCount = (obj, min, max, limit) =>
    Object.entries(obj)
      .filter(([, n]) => n >= min && n <= max)
      .sort((a, b) => b[1] - a[1])
      .slice(0, limit)
      .map(([k, n]) => `${k}  ×${n}`);

  /* ---- 2. 重复兄弟容器：消息列表最可能的形态 ---- */
  const sigCount = {};
  document.querySelectorAll("body *").forEach((el) => {
    const cls = (el.getAttribute("class") || "").trim().replace(/\s+/g, ".");
    if (!cls) return;
    const key = `${el.tagName.toLowerCase()}.${cls}`;
    sigCount[key] = (sigCount[key] || 0) + 1;
  });
  const repeated = topByCount(sigCount, 2, 60, 15);

  /* ---- 3. 疑似消息容器采样（含结构，文本脱敏） ---- */
  const samples = [];
  const seen = new Set();
  document.querySelectorAll("body *").forEach((el) => {
    const cls = (el.getAttribute("class") || "").trim();
    const hasRoleAttr = el.hasAttribute("data-role") || el.hasAttribute("data-message-author-role");
    const looksLikeMessage = interesting.test(cls) || hasRoleAttr;
    const textLen = (el.textContent || "").trim().length;
    if (!looksLikeMessage || textLen < 20 || textLen > 60000) return;
    if (el.querySelectorAll("*").length > 200) return;
    const key = `${el.tagName}:${cls.slice(0, 60)}`;
    if (seen.has(key)) return;
    seen.add(key);
    samples.push(describe(el, 0, true));
  });

  const out = {
    url: location.origin + location.pathname,
    title: document.title.slice(0, 80),
    counts: {
      totalElements: document.querySelectorAll("*").length,
      iframes: document.querySelectorAll("iframe").length,
      shadowHosts: Array.from(document.querySelectorAll("*")).filter((e) => e.shadowRoot).length,
    },
    /* AKC 当前配置的选择器命中数量（0 = 需要更新适配器） */
    currentSelectors: {
      "[data-testid='message-item'], .message-item": document.querySelectorAll("[data-testid='message-item'], .message-item").length,
      "[data-role]": document.querySelectorAll("[data-role]").length,
      "[data-message-id]": document.querySelectorAll("[data-message-id]").length,
      ".message-content, .markdown-body": document.querySelectorAll(".message-content, .markdown-body").length,
      "main, #root": document.querySelectorAll("main, #root").length,
      "a[href*='/chat/']": document.querySelectorAll("a[href*='/chat/']").length,
    },
    dataAttrs: topByCount(attrStat, 1, 500, 25),
    classHits: topByCount(classStat, 1, 500, 25),
    repeatedSiblingSignatures: repeated,
    messageSamples: samples.slice(0, 6),
    note: "文本已替换为 {n字} 占位符，不含任何对话内容",
  };

  const json = JSON.stringify(out, null, 2);
  console.log(json);
  try {
    copy(json);
    console.log("%c已复制到剪贴板，直接粘贴给维护者即可", "color:#1D9E75;font-weight:bold");
  } catch {
    console.log("（自动复制失败，请手动选中上面的 JSON 复制）");
  }
  return out;
})();
