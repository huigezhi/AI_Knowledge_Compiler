"""极简 SQL 迁移运行器。

设计取舍：MVP 不引入 Alembic，避免额外依赖与配置负担；但**每一次 schema 变更
仍然必须是可回滚的迁移文件**（``NNN_name.up.sql`` 与 ``NNN_name.down.sql`` 成对）。
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import Engine, text

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_UP_SUFFIX = ".up.sql"
_DOWN_SUFFIX = ".down.sql"


def _ensure_migration_table(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
            )
        )


def _apply_sql_file(engine: Engine, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    with engine.begin() as conn:
        for statement in _split_statements(sql):
            if statement.strip():
                conn.execute(text(statement))


def _split_statements(sql: str) -> list[str]:
    """按语句切分：普通语句以行尾 ``;`` 结束，触发器整体作为一个语句。

    触发器体内包含以 ``;`` 结尾的行，必须整体保留，否则会产生 "incomplete input"。
    """
    out: list[str] = []
    buffer: list[str] = []
    in_trigger = False
    for raw_line in sql.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("--"):
            continue
        buffer.append(raw_line)
        upper = line.upper()
        if upper.startswith("CREATE TRIGGER"):
            in_trigger = True
            continue
        if in_trigger:
            if upper == "END;":
                out.append("\n".join(buffer))
                buffer = []
                in_trigger = False
            continue
        if line.endswith(";"):
            out.append("\n".join(buffer))
            buffer = []
    if buffer:
        out.append("\n".join(buffer))
    return out


def applied_versions(engine: Engine) -> list[str]:
    _ensure_migration_table(engine)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version FROM schema_migrations ORDER BY version")).all()
    return [r[0] for r in rows]


def available_versions() -> list[str]:
    versions: list[str] = []
    for path in MIGRATIONS_DIR.glob(f"*{_UP_SUFFIX}"):
        match = re.match(r"^(\d{3})_", path.name)
        if match:
            versions.append(match.group(1))
    return sorted(set(versions))


def upgrade(engine: Engine, target: str | None = None) -> list[str]:
    """应用所有未执行的 up 迁移，返回本次执行的版本列表。"""
    _ensure_migration_table(engine)
    done = set(applied_versions(engine))
    executed: list[str] = []
    try:
        with engine.begin() as conn:
            for version in available_versions():
                if target is not None and version > target:
                    break
                if version in done:
                    continue
                up_file = _find_file(version, _UP_SUFFIX)
                for statement in _split_statements(up_file.read_text(encoding="utf-8")):
                    if statement.strip():
                        conn.execute(text(statement))
                conn.execute(
                    text("INSERT OR REPLACE INTO schema_migrations (version) VALUES (:v)"),
                    {"v": version},
                )
                executed.append(version)
    except Exception as exc:  # pragma: no cover - 迁移失败必须显式暴露
        raise RuntimeError(f"migration failed: {exc}") from exc
    return executed


def downgrade(engine: Engine, target: str) -> list[str]:
    """回滚到 ``target``（不含 target 本身）；``target="0"`` 表示全部回滚。"""
    _ensure_migration_table(engine)
    done = sorted(applied_versions(engine), reverse=True)
    rolled_back: list[str] = []
    try:
        with engine.begin() as conn:
            for version in done:
                if version <= target:
                    continue
                down_file = _find_file(version, _DOWN_SUFFIX)
                for statement in _split_statements(down_file.read_text(encoding="utf-8")):
                    if statement.strip():
                        conn.execute(text(statement))
                conn.execute(
                    text("DELETE FROM schema_migrations WHERE version = :v"), {"v": version}
                )
                rolled_back.append(version)
            if target == "0":
                conn.execute(text("DELETE FROM schema_migrations"))
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"rollback failed: {exc}") from exc
    return rolled_back


def _find_file(version: str, suffix: str) -> Path:
    matches = sorted(MIGRATIONS_DIR.glob(f"{version}_*{suffix}"))
    if not matches:
        raise FileNotFoundError(f"migration file for version {version} ({suffix}) not found")
    return matches[0]
