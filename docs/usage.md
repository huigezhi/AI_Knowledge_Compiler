# 使用指南（首次上手约 10 分钟）

本文按**真实使用顺序**走一遍：启动服务 → 加载扩展 → 采集 → 编译 → 写入 Obsidian → 审核。
命令均为 Windows（Git Bash / PowerShell 通用）；macOS / Linux 把 `.venv/Scripts/` 换成 `.venv/bin/`。

---

## 第 0 步：准备

| 需要 | 说明 |
| --- | --- |
| Chrome / Edge 116+ | Side Panel API 的最低版本 |
| 一个 Obsidian Vault | 任意空文件夹即可，建议新建 `E:\Obsidian\AKC-Vault` |
| Claude API Key（可选） | 只有"编译"才需要；不配置也能正常采集与存档 |

---

## 第 1 步：启动本地服务

```bash
cd apps/backend
./.venv/Scripts/python.exe -m akc
```

看到日志 `backend_started` 即启动成功。验证：

```bash
curl http://127.0.0.1:38127/api/v1/health
# {"status":"ok","service":"akc-backend","version":"0.1.0",...}
```

首次启动会做三件事：应用数据库迁移、启动后台任务 worker、
在 `apps/backend/data/auth_token` 生成**本地访问令牌**。

服务只在 `127.0.0.1:38127` 监听，不对外暴露。

---

## 第 2 步：配置 Vault 与 Claude（可选但推荐）

复制 `.env.example` 为 `apps/backend/.env`，按需填写：

```env
AKC_VAULT_PATH=E:/Obsidian/AKC-Vault          # 必填才能写入 Obsidian
AKC_CLAUDE_ENABLED=true                        # 想编译就设为 true
AKC_CLAUDE_MODEL=<你的模型 ID>                  # 例如 claude-sonnet-4-5
AKC_CLAUDE_API_KEY=sk-ant-...                  # 绝对不要提交到 Git
```

改完**重启服务**生效。检查：

```bash
curl http://127.0.0.1:38127/api/v1/obsidian/status
# {"vault_path":"E:/Obsidian/AKC-Vault","configured":true,...}
```

> 模型 ID 一律来自配置，代码里没有硬编码的模型名。

---

## 第 3 步：加载扩展

```bash
cd apps/extension
npm install     # 首次
npm run build   # 产物在 apps/extension/dist
```

1. 打开 `chrome://extensions` → 右上角开启「开发者模式」
2. 「加载已解压的扩展程序」→ 选择 `apps/extension/dist`
3. 建议点扩展卡片上的图钉，把 AKC 固定到工具栏

改代码后需要重新 `npm run build`（或 `npm run dev` 监听构建），再在扩展页点刷新。

---

## 第 4 步：把令牌填进扩展

1. 打开 `apps/backend/data/auth_token`，复制里面的字符串
2. 右键扩展图标 → 选项（Options）
3. 填写：
   - 后端地址：`http://127.0.0.1:38127`
   - 本地访问令牌：刚才复制的那一串
4. 点「测试连接」，显示"已连接"即成功
5. 保存设置

> 这一步不能跳过：浏览器里任意网页都能请求 localhost，
> 令牌用于阻止伪造请求（写操作没有令牌会被返回 401）。

---

## 第 5 步：采集对话

打开任意受支持平台（chatgpt.com / claude.ai / chat.deepseek.com / doubao.com / chatglm.cn），
进入一个具体会话，然后：

1. 点扩展图标打开 **Side Panel**
2. 顶部会显示识别到的平台与适配器健康状态
   - 显示「正常」→ 可以直接用
   - 显示「降级 / 异常」→ 平台页面结构变了，见文末排查
3. 点「保存当前」→ 原始对话入库
   - 勾选了"保存时同时写 Raw 到 Obsidian"，还会生成 `01_Raw/<平台>/<标题>-<日期>.md`
4. 点「保存 + 编译」→ 入库后自动进入编译队列

**历史批量同步**：点「加载」列出历史会话 → 勾选（或全选）→ 「批量同步」。
同步时会显示"已处理 / 总数、成功 / 失败"。

> 批量同步需要逐条打开会话页面，当前实现会在页面不匹配时提示你打开对应会话。

---

## 第 6 步：编译（需要第 2 步的 Claude 配置）

在 Side Panel 点「保存 + 编译」，或直接调用接口：

```bash
TOKEN=$(cat apps/backend/data/auth_token)
curl -X POST http://127.0.0.1:38127/api/v1/jobs/compile \
  -H "Content-Type: application/json" -H "X-AKC-Token: $TOKEN" \
  -d '{"conversation_id":"c1"}'

curl http://127.0.0.1:38127/api/v1/jobs/<返回的 job_id>
```

编译阶段会真实展示：排队 → 抽取知识 → 关联已有知识 → 合并去重 → 写入。
**不会显示虚假百分比**。

编译结果：

- 高置信度且无冲突 → `candidate`
- 低置信度（< 0.6）或与已有知识冲突 → `review`（等待你确认）

查看：

```bash
curl "http://127.0.0.1:38127/api/v1/knowledge?limit=20"
```

---

## 第 7 步：写入 Obsidian

Side Panel 点「写入 Obsidian」，或：

```bash
curl -X POST http://127.0.0.1:38127/api/v1/obsidian/sync \
  -H "Content-Type: application/json" -H "X-AKC-Token: $TOKEN" \
  -d '{"knowledge_ids":["k_xxx"]}'
```

产物：

```
<E:\Obsidian\AKC-Vault>/
├── 01_Raw/DeepSeek/SQL 优化-2026-09-19.md
└── 03_Knowledge/Methods/sql-查询性能优化方法.md
```

Knowledge 笔记带 YAML frontmatter（状态、置信度、版本、compiler、prompt_version、model）
和 `## 来源证据` 段落里的 `[[Wiki Link]]`，点进去能跳回原始对话。

**安全策略**：AKC 只覆盖由 AKC 自己生成的文件；
如果你手动改过某个笔记，再次同步时会跳过它并在响应里给出原因（`skipped`）。

---

## 第 8 步：审核

```bash
# 确认某条知识（candidate/review → verified）
curl -X POST http://127.0.0.1:38127/api/v1/knowledge/k_xxx/review \
  -H "Content-Type: application/json" -H "X-AKC-Token: $TOKEN" \
  -d '{"action":"verify","reason":"我已核实"}'
```

- Side Panel 里每条待确认知识右侧有「确认」按钮
- 动作：`verify` / `reject` / `archive` / `review`
- 合并：`POST /api/v1/knowledge/{id}/merge` 指定 `target_knowledge_id`
- 撤销合并：`POST /api/v1/knowledge/{id}/unmerge`

状态机：`candidate → review → verified → archived`，`verified ⇄ merged`。
非法流转会返回 409 并告诉你允许的目标状态。

---

## 日常使用小抄

```bash
make backend-run     # 起服务
make ext-build       # 打包扩展
make test            # 全量测试
```

| 想做的事 | 操作 |
| --- | --- |
| 只存档对话，不调用 Claude | 不配 `AKC_CLAUDE_ENABLED`，只用「保存当前」 |
| 换 Vault | 改 `.env` 的 `AKC_VAULT_PATH`，重启服务 |
| 换模型 | 改 `.env` 的 `AKC_CLAUDE_MODEL`，重启服务 |
| 导出一条对话 | `GET /api/v1/conversations/{id}/export?fmt=markdown\|json` |
| 关键词检索知识 | `GET /api/v1/knowledge/search?q=索引` |
| 看任务为什么失败 | `GET /api/v1/jobs?status=failed` 里的 `error_code` |

---

## 排查

| 现象 | 原因与处理 |
| --- | --- |
| Side Panel 显示"未检测到会话" | 没在会话详情页；打开一个具体会话再试 |
| 适配器显示「降级 / 异常」 | 平台 DOM 变了：跑 `npm run fixtures` 后看哪个用例失败，更新 `SELECTORS`，见 `docs/adapters.md` |
| 扩展报"无法连接本地 AKC 服务" | 后端没启动，或 Options 里地址填错；点「测试连接」确认 |
| 写入返回 401 | 令牌不对：重新复制 `apps/backend/data/auth_token` |
| 导入报 422 | 数据不符合 Schema，通常是适配器需要更新 |
| 编译一直 pending | 后台 worker 未启动（看启动日志 `job_worker_started`），或队列里有失败任务 |
| Obsidian 里没看到文件 | 检查 `AKC_VAULT_PATH` 是否配置（`GET /api/v1/obsidian/status`） |
| 想重新生成令牌 | 删除 `apps/backend/data/auth_token` 后重启服务 |

---

## 隐私提醒

- 原始对话、知识库、数据库全在本机；
- 只有点「编译」时才会把会话上下文发给 Claude API；
- 扩展不保存 API Key，日志不记录令牌与完整外发内容。
