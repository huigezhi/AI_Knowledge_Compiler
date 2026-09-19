"""本地配置读写。

读取 = 环境变量默认值 + 数据库覆盖值；写入只接受白名单键，且**绝不返回密钥明文**。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy.orm import Session

from akc.deps import SessionDep, SettingsDep
from akc.repositories import audit, settings as settings_repo
from akc.schemas.api import SettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])

# 允许读取的键 -> 从 Settings 取值的方式
_READABLE_ENV_KEYS = (
    "backend_url",
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
)


@router.get("")
def get_settings(session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    overrides = settings_repo.get_all(session)
    values: dict[str, Any] = {
        "backend_url": f"http://{settings.host}:{settings.port}",
        "claude_enabled": settings.claude_enabled,
        "claude_model": settings.claude_model,
        "claude_max_context_tokens": settings.claude_max_context_tokens,
        "vault_path": str(settings.vault_path) if settings.vault_path else None,
        "vault_raw_folder": settings.vault_raw_folder,
        "vault_knowledge_folder": settings.vault_knowledge_folder,
        "vault_inbox_folder": settings.vault_inbox_folder,
        "auto_compile": settings.auto_compile,
        "auto_merge_verified": settings.auto_merge_verified,
        "require_review_for_conflicts": settings.require_review_for_conflicts,
        "log_level": settings.log_level,
    }
    for key, stored in overrides.items():
        if key in values:
            values[key] = (stored or {}).get("value", values[key])
    return {
        "values": values,
        "claude_api_key_configured": bool(settings.claude_api_key),
        "readable_keys": list(_READABLE_ENV_KEYS),
        "writable_keys": sorted(settings_repo.WRITABLE_KEYS),
        "env": settings.env,
    }


@router.put("")
def update_settings(
    payload: SettingsUpdate, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    rejected = settings_repo.put_many(session, payload.values)
    audit.record(
        session,
        log_id=f"audit_settings_{id(payload)}",
        event_type="settings.updated",
        entity_type="settings",
        detail={"keys": sorted(payload.values), "rejected": sorted(rejected)},
    )
    session.commit()
    if "vault_path" in payload.values and payload.values["vault_path"]:
        # 运行期热更新 vault 路径，避免必须重启才能写 Obsidian。
        object.__setattr__(settings, "vault_path", _as_path(payload.values["vault_path"]))
    return {"updated": sorted(k for k in payload.values if k not in rejected), "rejected": sorted(rejected)}


def _as_path(value: Any):
    from pathlib import Path

    return Path(str(value)) if value else None
