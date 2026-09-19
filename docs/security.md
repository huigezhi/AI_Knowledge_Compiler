# 安全、隐私与数据完整性

## 1. 威胁模型

| 威胁 | 缓解措施 |
| --- | --- |
| 浏览器里任意网页伪造本地请求 | 写请求强制 `X-AKC-Token`（随机 32 字节，存 `data/auth_token`）；只监听 `127.0.0.1` |
| 跨站读取本地 API | CORS 显式来源（`AKC_CORS_ORIGINS`），生产禁止 `*` |
| 密钥泄露到代码库 | API Key 只读环境变量；`.env` 已 git-ignore；`PUT /settings` 白名单拒绝密钥类字段 |
| 密钥泄露到浏览器 | 扩展不保存 API Key，只保存后端地址与本地 token |
| 日志泄露 | 不记录 API Key / Cookie / Authorization 头 / 完整外发 payload，只记输入摘要 |
| 响应被嵌套/嗅探 | `X-Content-Type-Options`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer` |

## 2. 扩展权限最小化

```jsonc
"permissions": ["sidePanel", "storage", "activeTab", "scripting"],
"host_permissions": ["http://127.0.0.1:38127/*", "http://localhost:38127/*"],
"optional_host_permissions": ["http://*/*", "https://*/*"]
```

`optional_host_permissions` **不会自动授予任何权限**：只有在用户于设置页点「保存／测试连接」
（即用户手势）时，扩展才会针对所填地址调用 `chrome.permissions.request()`，
由浏览器弹窗让用户确认。拒绝则保存失败并给出明确提示（见 `src/shared/permissions.ts`）。

- 不申请 `<all_urls>`，只对 5 个 AI 平台注入 content script；
- 不读取与采集无关的 `localStorage` / cookie；
- 不修改第三方站点数据，不代用户发送消息；
- 只有用户点击「编译」时才把上下文发往 Claude API。

## 3. 数据完整性

| 原则 | 落地 |
| --- | --- |
| Raw 永不被编译覆盖 | 编译只写 `knowledge*` 表；`messages` 无删除路径 |
| 幂等 | `conversations(provider_id, external_id)`、`messages(conversation_id, external_id)`、`jobs(idempotency_key)` 唯一约束 |
| 二次幂等 | `content_hash` 未变则跳过更新 |
| 可回滚 | Schema 与知识更新都保留 `version`；数据库迁移提供 `*.down.sql` |
| 不静默覆盖 | `verified` 知识与候选冲突 → `review`；Vault 中人工文件 → `OBSIDIAN_CONFLICT` |
| 可追溯 | `knowledge_sources` 强制溯源；`compile_runs` 记录 model/prompt/compiler/adapter 版本；`audit_logs` 记录状态变更 |
| 失败不丢数据 | 导入失败不影响已入库数据；Vault 写入失败自动降级为 `WRITE_OBSIDIAN` 任务并计入 `warnings` |

## 4. 破坏性操作清单

以下操作都需要**显式用户动作**或开关，且尽可能可逆：

| 操作 | 保护 |
| --- | --- |
| 知识合并 | 需要指定目标条目；被合并项标记 `merged`，可 `unmerge` |
| 状态流转 | 状态机校验，非法转换返回 409 |
| Vault 覆盖 | 内容无变化不落盘；非 AKC 文件拒绝覆盖 |
| 批量同步 | 逐条入库，失败计数进入 `sync_runs.stats_json` |

## 5. 上报与响应

发现安全问题请通过 GitHub Issues 私下联系维护者，
**不要**在 issue 中粘贴密钥、令牌或包含原始对话的日志片段。
