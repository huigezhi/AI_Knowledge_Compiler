#!/usr/bin/env node
/**
 * 生成 Adapter 回归 fixtures（需求文档 §16.2）：
 * 每个平台 6 类页面 —— 最小对话 / 多轮 / 代码块 / 表格 / 长对话 / 异常页面。
 *
 * ⚠️ 本文件里的 DOM 结构必须与 ``src/adapters/*.ts`` 的 SELECTORS 保持一致。
 *    平台页面变化时的正确顺序：更新 SELECTORS → 更新本生成器 → ``npm run fixtures`` → 跑单测。
 *    fixtures 已提交到仓库，保证回归可复现，禁止只依赖线上页面测试。
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = resolve(here, "..", "tests", "fixtures");

/** 各平台 DOM 结构定义（与 adapters 中的 SELECTORS 对应）。 */
const PROVIDERS = {
  chatgpt: {
    href: (id) => `/c/${id}`,
    turn: (i) => `data-testid="conversation-turn-${i}"`,
    message: (role, id) => `data-message-author-role="${role}" data-message-id="${id}"`,
    withChatTitle: false,
  },
  claude: {
    href: (id) => `/chat/${id}`,
    turn: (i) => `data-test-render-count="${i}"`,
    message: (role, id) => `data-message-author-role="${role}" data-message-id="${id}"`,
    withChatTitle: false,
  },
  deepseek: {
    href: (id) => `/chat/${id}`,
    turn: () => `data-testid="chat-turn"`,
    message: (role, id) => `data-message-id="${id}" data-role="${role}"`,
    withChatTitle: true,
  },
  doubao: {
    href: (id) => `/chat/${id}`,
    turn: () => `data-testid="message-item"`,
    message: (role, id) => `data-role="${role}" data-message-id="${id}"`,
    withChatTitle: true,
  },
  zhipu: {
    href: (id) => `/chat/${id}`,
    turn: () => `class="chat-item"`,
    message: (role, id) => `data-role="${role}" data-message-id="${id}"`,
    withChatTitle: true,
  },
};

const HISTORY = [
  ["aaaaaaaaaa", "SQL 性能优化"],
  ["bbbbbbbbbb", "CTE 递归查询讨论"],
  ["cccccccccc", "索引失效排查"],
];

function historyNav(provider) {
  const items = HISTORY.map(
    ([id, title]) =>
      `      <a href="${provider.href(id)}"><span class="akc-history-title">${title}</span></a>`,
  ).join("\n");
  return `    <nav class="akc-history">\n${items}\n    </nav>`;
}

function messageBlock(provider, role, id, bodyHtml, timestamp) {
  return [
    `    <div ${provider.turn()}>`,
    `      <div ${provider.message(role, id)}>`,
    `        <div class="akc-content">`,
    bodyHtml,
    `        </div>`,
    `        <time datetime="${timestamp}"></time>`,
    `      </div>`,
    `    </div>`,
  ].join("\n");
}

const CODE_BODY = `        <p>可以用下面这段 SQL 复现：</p>
        <pre><code class="language-sql">EXPLAIN ANALYZE
SELECT o.id, o.total
FROM orders o
WHERE o.created_at &gt;= '2026-01-01';</code></pre>`;

const TABLE_BODY = `        <p>三种方案对比：</p>
        <table>
          <tr><th>方案</th><th>耗时</th><th>风险</th></tr>
          <tr><td>加索引</td><td>低</td><td>写放大</td></tr>
          <tr><td>改 SQL</td><td>中</td><td>语义变化</td></tr>
          <tr><td>分区表</td><td>高</td><td>迁移复杂</td></tr>
        </table>`;

function buildConversationHtml(provider, { title, messages }) {
  const head = [
    "<!DOCTYPE html>",
    '<html lang="zh-CN">',
    "<head>",
    '  <meta charset="utf-8" />',
    `  <title>${title}</title>`,
    "</head>",
    "<body>",
    '  <main id="chat-container">',
  ];
  if (provider.withChatTitle) {
    head.push(`    <div class="chat-title">${title}</div>`);
  }
  head.push(historyNav(provider));
  const body = messages.map((m) =>
    messageBlock(provider, m.role, m.id, m.body, m.at ?? "2026-09-18T20:31:00+08:00"),
  );
  return [...head, ...body, "  </main>", "</body>", "</html>", ""].join("\n");
}

function buildErrorHtml(provider, title) {
  return [
    "<!DOCTYPE html>",
    '<html lang="zh-CN">',
    "<head>",
    '  <meta charset="utf-8" />',
    `  <title>${title}</title>`,
    "</head>",
    "<body>",
    '  <main id="chat-container">',
    '    <div class="empty-state">页面结构已变化 / 会话加载失败</div>',
    "  </main>",
    "</body>",
    "</html>",
    "",
  ].join("\n");
}

function buildFixtures() {
  const written = [];
  for (const [name, provider] of Object.entries(PROVIDERS)) {
    const cases = {};

    cases.minimal = {
      title: "SQL 性能优化",
      messages: [
        { role: "user", id: `${name}-u1`, body: "        怎么优化这条 SQL？" },
        {
          role: "assistant",
          id: `${name}-a1`,
          body: "        先看执行计划，再决定改 SQL 还是加索引。",
        },
      ],
    };

    cases.multi = {
      title: "CTE 递归查询讨论",
      messages: [
        { role: "user", id: `${name}-u1`, body: "        CTE 和子查询有什么区别？" },
        {
          role: "assistant",
          id: `${name}-a1`,
          body: "        CTE 可读性更好；递归场景必须用 CTE。",
        },
        { role: "user", id: `${name}-u2`, body: "        性能上呢？" },
        {
          role: "assistant",
          id: `${name}-a2`,
          body: "        大多数情况下优化器会内联展开，差异不大。",
        },
        { role: "user", id: `${name}-u3`, body: "        什么时候会变慢？" },
        {
          role: "assistant",
          id: `${name}-a3`,
          body: "        递归层级深或需要物化时，需要显式控制。",
        },
      ],
    };

    cases.code = {
      title: "执行计划分析方法",
      messages: [
        { role: "user", id: `${name}-u1`, body: "        怎么拿到执行计划？" },
        { role: "assistant", id: `${name}-a1`, body: CODE_BODY },
      ],
    };

    cases.table = {
      title: "三种优化方案对比",
      messages: [
        { role: "user", id: `${name}-u1`, body: "        这几个方案怎么选？" },
        { role: "assistant", id: `${name}-a1`, body: TABLE_BODY },
      ],
    };

    cases.long = {
      title: "长对话压力测试",
      messages: Array.from({ length: 20 }, (_, index) => ({
        role: index % 2 === 0 ? "user" : "assistant",
        id: `${name}-m${index + 1}`,
        body: `        第 ${index + 1} 条消息：讨论 SQL 优化的第 ${index + 1} 个细节。`,
        at: `2026-09-18T20:${String(31 + index).padStart(2, "0")}:00+08:00`,
      })),
    };

    for (const [kind, spec] of Object.entries(cases)) {
      const file = resolve(OUT_DIR, `${name}-${kind}.html`);
      writeFileSync(file, buildConversationHtml(provider, spec), "utf-8");
      written.push(file);
    }

    const errorFile = resolve(OUT_DIR, `${name}-error.html`);
    writeFileSync(errorFile, buildErrorHtml(provider, "加载失败"), "utf-8");
    written.push(errorFile);
  }
  return written;
}

mkdirSync(OUT_DIR, { recursive: true });
const files = buildFixtures();
console.log(`generated ${files.length} fixtures into ${OUT_DIR}`);
