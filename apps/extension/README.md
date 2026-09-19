# @akc/extension

Chrome MV3 扩展：在 ChatGPT / Claude / DeepSeek / 豆包 / 智谱清言 页面里采集对话，
交给本地后端（`apps/backend`）编译并写入 Obsidian。

## 开发

```bash
npm install
npm run typecheck   # tsc --noEmit
npm run test        # vitest（54 个用例：adapter fixtures / API 客户端 / background 路由）
npm run build       # 产物 dist/
npm run fixtures    # 重新生成 adapter 回归 fixtures
```

加载未打包扩展：`chrome://extensions` → 开发者模式 →「加载已解压的扩展程序」→ 选择 `dist`。

## 目录

| 路径 | 职责 |
| --- | --- |
| `src/background/index.ts` | Service Worker：消息路由 + `chrome.sidePanel` / `chrome.tabs` 能力 |
| `src/content/index.ts` | 注入到平台页面执行 Adapter，**只读 DOM** |
| `src/sidepanel/` | Side Panel：平台识别、保存、历史批量、编译进度、审核 |
| `src/options/` | 设置页：后端地址、本地 token、采集策略、日志级别 |
| `src/shared/` | 类型化 API 客户端、设置、消息协议、日志 |
| `src/adapters/` | 5 个平台适配器 + selector 常量表 + 注册表 |
| `tests/fixtures/` | 每平台 6 类回归 fixture（30 个 HTML，由 `scripts/gen-fixtures.mjs` 生成） |

## 构建为什么拆成两次

MV3 的 content script 需要 IIFE，而 service worker / 页面用 ESM，
同一份 rollup 输出无法混用两种格式，因此：

- `vite.config.ts` → `background/index.js`（ESM）、`sidepanel/`、`options/`
- `vite.content.config.ts` → `content.js`（IIFE）

`public/manifest.json` 原样复制到 `dist/`。

## 前端边界约定

- **4xx 不重试**，映射为中文可读文案；**5xx 指数退避重试最多 3 次**；
- 全部失败 → `OfflineError`，UI 提示“无法连接本地 AKC 服务”；
- 所有写请求自动附带 `X-AKC-Token`；
- 编译中展示真实阶段（排队 / 抽取 / 关联 / 合并 / 写入），**不显示虚假百分比**。

## 新增一个平台

1. `src/adapters/<provider>.ts`：导出 `SELECTORS`、`ADAPTER_VERSION`、`create<Provider>Adapter(context?)`；
2. 在 `src/adapters/registry.ts` 的 `FACTORIES` 注册；
3. 在 `scripts/gen-fixtures.mjs` 的 `PROVIDERS` 增加 DOM 结构定义 → `npm run fixtures`；
4. 在 `public/manifest.json` 的 `content_scripts.matches` 增加来源；
5. 同步后端 `apps/backend/akc/services/provider_registry.py`（`adapter_version` / `origins`）；
6. `npm run test` 全绿后提交。

**不要**在适配器之外的任何文件里写 selector。
