"""settings 与 audit_logs 访问。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from akc.db.models import Setting

# 允许通过 API 持久化的设置键（其余一律视为只读，避免写入内部状态）。
WRITABLE_KEYS = {
    "backend_url",
    "llm_enabled",
    "llm_provider",
    "llm_model",
    "llm_max_context_tokens",
    # 兼容旧键名
    "claude_enabled",
    "claude_model",
    "claude_max_context_tokens",
    "vault_path",
    "vault_raw_folder",
    "vault_knowledge_folder",
    "vault_inbox_folder",
    "auto_compile",
    "auto_merge_verified",
    "require_review_for_conflicts",
    "log_level",
}


def get_all(session: Session) -> dict[str, Any]:
    rows = session.scalars(select(Setting)).all()
    return {row.key: dict(row.value_json or {}) for row in rows}


def get(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(Setting, key)
    if row is None:
        return default
    return (row.value_json or {}).get("value", default)


def put(session: Session, key: str, value: Any) -> None:
    """写入设置。值以 ``{"value": ...}`` 包装，便于将来扩展元信息。"""
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value_json={"value": value}))
    else:
        row.value_json = {"value": value}
    session.flush()


def put_many(session: Session, values: dict[str, Any]) -> dict[str, Any]:
    """批量写入，自动过滤不可写键。返回被忽略的键。"""
    rejected = {k: v for k, v in values.items() if k not in WRITABLE_KEYS}
    for key, value in values.items():
        if key in WRITABLE_KEYS:
            put(session, key, value)
    return rejected


# 审计日志位于 ``akc.repositories.audit``，此处只负责 settings 表。
