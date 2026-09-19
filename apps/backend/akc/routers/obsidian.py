"""Obsidian Vault 同步。

写入策略见 ``services/obsidian.py``：原子替换 + 人工修改冲突检测。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy.orm import Session

from akc.deps import SessionDep, SettingsDep
from akc.repositories import conversation as conv_repo
from akc.schemas.api import ObsidianSyncRequest
from akc.services import obsidian

router = APIRouter(prefix="/obsidian", tags=["obsidian"])


@router.get("/status")
def status(settings: SettingsDep) -> dict[str, object]:
    return {
        "vault_path": str(settings.vault_path) if settings.vault_path else None,
        "configured": bool(settings.vault_path),
        "raw_folder": settings.vault_raw_folder,
        "knowledge_folder": settings.vault_knowledge_folder,
        "inbox_folder": settings.vault_inbox_folder,
    }


@router.post("/sync")
def sync(
    payload: ObsidianSyncRequest, session: SessionDep, settings: SettingsDep
) -> dict[str, object]:
    if not settings.vault_path:
        from akc.errors import ObsidianVaultNotConfiguredError

        raise ObsidianVaultNotConfiguredError("obsidian vault path is not configured")

    # 知识落盘统一走 services（编译任务的自动落盘也用同一份逻辑）
    result = obsidian.sync_knowledge(session, settings, payload.knowledge_ids)
    written = list(result["written"])
    skipped = list(result["skipped"])

    for conversation_id in payload.conversation_ids:
        conv = conv_repo.get(session, conversation_id)
        if conv is None:
            skipped.append({"id": conversation_id, "reason": "conversation not found"})
            continue
        normalized = conv_repo.to_dict(conv, with_messages=True)
        markdown = obsidian.build_raw_markdown(normalized)
        date_part = (conv.created_at or conv.updated_at).strftime("%Y-%m-%d")
        path = (
            obsidian.VaultLayout(
                vault_path=settings.vault_path,
                raw_folder=settings.vault_raw_folder,
                knowledge_folder=settings.vault_knowledge_folder,
                inbox_folder=settings.vault_inbox_folder,
            ).raw_dir(conv.provider_id)
            / f"{obsidian.slugify(conv.title)}-{date_part}.md"
        )
        try:
            target, changed = obsidian.write_markdown(path, markdown)
        except Exception as exc:  # noqa: BLE001
            skipped.append({"id": conversation_id, "reason": str(exc)})
            continue
        conv.raw_payload_ref = str(target)
        written.append({"id": conversation_id, "path": str(target), "changed": changed})

    session.commit()
    return {"written": written, "skipped": skipped, "vault_path": str(settings.vault_path)}


def _wiki_link(session: Session, message_id: str) -> str | None:
    """把 Raw Message 映射为其所属会话的 Wiki Link（保持溯源可点击）。"""
    from akc.repositories import message as msg_repo

    message = msg_repo.get(session, message_id)
    if message is None:
        return None
    conv = conv_repo.get(session, message.conversation_id)
    if conv is None:
        return None
    date_part = (conv.created_at or conv.updated_at).strftime("%Y-%m-%d")
    return f"[[{conv.provider_id.title()} - {conv.title} - {date_part}]]"
