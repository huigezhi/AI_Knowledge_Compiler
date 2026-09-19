# 本地开发

## 1. 环境要求

| 组件 | 版本 |
| --- | --- |
| Node.js | 20+ |
| Python | 3.12+ |
| Chrome / Edge | 116+（Side Panel API） |
| Obsidian | 任意版本（仅作为 Vault 目录） |

## 2. 首次初始化

```bash
make bootstrap
# 等价于：
#   cd apps/backend   && python -m venv .venv && ./.venv/Scripts/python -m pip install -e ".[dev]"
#   cd apps/extension && npm install
```

> 若 pip 使用了不可用的镜像源，可临时指定官方源：
> `pip install -i https://pypi.org/simple -e ".[dev]"`

## 3. 常用命令

```bash
make backend-run     # 启动后端 http://127.0.0.1:38127
make backend-test    # pytest
make ext-build       # 构建扩展（含 tsc 类型检查）
make ext-test        # vitest
make fixtures        # 重新生成 adapter fixtures
make test            # 前后端全量测试
```

Windows 下可直接执行 `apps/backend/.venv/Scripts/python -m akc`。

## 4. 配置

复制仓库根目录 `.env.example` 为 `apps/backend/.env`：

| 变量 | 说明 |
| --- | --- |
| `AKC_HOST` / `AKC_PORT` | 默认 `127.0.0.1` / `38127` |
| `AKC_DATA_DIR` / `AKC_DATABASE_URL` | SQLite 位置 |
| `AKC_AUTH_TOKEN` | 留空则自动生成到 `data/auth_token` |
| `AKC_CORS_ORIGINS` | 逗号分隔的显式来源 |
| `AKC_VAULT_PATH` | Obsidian Vault 绝对路径 |
| `AKC_CLAUDE_ENABLED` / `_MODEL` / `_API_KEY` | 启用后两者必填 |
| `AKC_JOB_BACKOFF_SECONDS` | 默认 `2,5,15` |

配置在**启动时集中校验**，有问题直接 fail fast（例如启用编译器却没给 model）。

## 5. 加载扩展

1. `cd apps/extension && npm run build`
2. `chrome://extensions` → 开发者模式 → 加载已解压的扩展程序 → 选择 `apps/extension/dist`
3. 修改代码后重新 `npm run build`（或 `npm run dev` 监听构建），再点扩展卡片上的刷新

## 6. 测试策略

| 层 | 位置 | 做法 |
| --- | --- | --- |
| 纯函数（哈希/归一化/Merge Planner） | `apps/backend/tests/test_hasher.py`、`test_normalizer.py`、`test_merge_planner.py` | 直接断言，无 IO |
| 仓储 / 服务 | `test_import_dedup.py`、`test_jobs.py` | 真实 SQLite（每个测试独立临时库 + 迁移） |
| HTTP | `test_api_smoke.py` | FastAPI `TestClient` |
| 外部依赖隔离 | `test_compile_pipeline.py` | `httpx.MockTransport` 假 Claude 响应 |
| Adapter | `apps/extension/src/adapters/__tests__` | jsdom + fixtures |
| 前端边界 | `apps/extension/src/shared/__tests__`、`background/__tests__` | mock fetch / chrome API |

原则：**单测不 mock 服务层**，集成测试用真实数据库（临时文件），
外部 API 用传输层假实现而不是给业务函数打补丁。

## 7. 里程碑（M0 → M6）

| 阶段 | 交付 | 状态 |
| --- | --- | --- |
| M0 | monorepo、CI、`.editorconfig`、`.env.example`、CLAUDE.md、SQL 迁移框架 | ✅ |
| M1 | Universal Schema、13 张表、FTS5、仓储/服务/路由、错误与日志体系 | ✅ |
| M2 | 5 个 Provider Adapter + selector 常量 + 30 份 fixtures | ✅ |
| M3 | MV3 扩展：Side Panel / Options / background / content + 类型化客户端 | ✅ |
| M4 | 编译流水线：Prompt 版本化、Schema 校验、任务队列与重试 | ✅ |
| M5 | Obsidian 写入、溯源 Wiki Links、审核与合并 | ✅ |
| M6 | 全量回归（80 后端 + 54 前端）、安全加固、构建与文档 | ✅ |

每完成一个阶段都必须保证测试通过并产出可运行版本。

## 8. 调试技巧

- 后端日志默认 JSON，带 `request_id`；扩展日志带 `scope: "akc-extension"`；
- `GET /api/v1/obsidian/status` 可确认 Vault 是否配置成功；
- Adapter 异常时先看 `dom_version`：`turns:0` 通常意味着 selector 已失效；
- 任务卡住时查 `GET /api/v1/jobs?status=failed` 里的 `error_code` 与 `attempts`。
