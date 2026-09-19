# @akc/backend

AI Knowledge Compiler 的本地后端：会话入库、Claude 知识编译、Obsidian 写入。

**只监听 `127.0.0.1`**，所有写请求需携带 `X-AKC-Token`。

## 运行

```bash
python -m venv .venv
./.venv/Scripts/python -m pip install -e ".[dev]"   # Windows
# source .venv/bin/activate && pip install -e ".[dev]"   # macOS / Linux
python -m akc            # http://127.0.0.1:38127
```

配置见仓库根目录 `.env.example`（复制为 `apps/backend/.env`），
全部变量在 `akc/config.py` 中集中校验，非法配置启动时直接 fail fast。

## 测试

```bash
python -m pytest -q
```

80 个用例覆盖：哈希与归一化、Schema 边界、导入幂等与去重、任务队列重试/死信、
Merge Planner 五分支、Obsidian 原子写入与冲突、API 冒烟、编译流水线（假 Claude 传输层）。

## 分层

```
routers/      →  解析请求、调用 service、格式化响应（不含业务规则）
services/     →  业务规则与编排（不依赖 HTTP 类型）
repositories/ →  数据访问
compiler/     →  Claude 客户端、Prompt 模板（版本化）、输出 Schema 校验
db/           →  SQLAlchemy 模型 + 可回滚 SQL 迁移（up/down 成对）
```

## 关键文件

| 文件 | 职责 |
| --- | --- |
| `akc/config.py` | 环境变量 → `Settings`，启动校验，本地 token 生成 |
| `akc/errors.py` | 类型化错误 + 错误码，全局 handler 统一输出 |
| `akc/db/migrate.py` | 迁移运行器（`schema_migrations` 表） |
| `akc/services/import_service.py` | 导入幂等、Raw 写入、失败降级 |
| `akc/services/compile_service.py` | 编译流水线编排 |
| `akc/services/merge_planner.py` | create/update/merge/ignore/review 判定 |
| `akc/services/obsidian.py` | Vault 模板、原子写入、人工修改冲突检测 |
| `akc/job_handlers.py` | 任务类型与处理器的注册点 |

## 注意

- 数据库变更必须写 `db/migrations/*.up.sql` 与配对的 `*.down.sql`；
- 知识更新递增 `version`，Raw 消息永不因编译失败而删除；
- 日志只记录输入摘要，绝不记录 API Key 与完整外发 payload。
