"""Obsidian Vault 同步。

写入策略见 ``services/obsidian.py``：原子替换 + 人工修改冲突检测。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy.orm import Session

from akc.deps import SessionDep, SettingsDep
from akc.errors import NotFoundError
from akc.repositories import conversation as conv_repo, knowledge as kn_repo
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

    layout = obsidian.VaultLayout(
        vault_path=settings.vault_path,
        raw_folder=settings.vault_raw_folder,
        knowledge_folder=settings.vault_knowledge_folder,
        inbox_folder=settings.vault_inbox_folder,
    )
    written: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for knowledge_id in payload.knowledge_ids:
        item = kn_repo.get(session, knowledge_id)
        if item is None:
            raise NotFoundError("knowledge not found", details={"id": knowledge_id})
        source_message_ids = [
            link.message_id for link in kn_repo.sources_for(session, knowledge_id)
        ]
        source_links = [_wiki_link(session, mid) for mid in source_message_ids]
        markdown = obsidian.build_knowledge_markdown(
            title=item.title,
            knowledge_type=item.knowledge_type,
            status=item.status,
            summary=item.summary,
            body_markdown=item.markdown,
            confidence=item.confidence,
            topics=list(item.topics_json or []),
            entities=list(item.entities_json or []),
            source_links=[link for link in source_links if link],
            created_at=item.created_at.isoformat() if item.created_at else "",
            updated_at=item.updated_at.isoformat() if item.updated_at else "",
            prompt_version=item.prompt_version,
            model=item.model,
            version=item.version,
        )
        path = layout.knowledge_dir(item.knowledge_type) / f"{item.slug}.md"
        try:
            target, changed = obsidian.write_markdown(path, markdown)
        except Exception as exc:  # noqa: BLE001 - 单条失败不影响其它条目
            skipped.append({"id": knowledge_id, "reason": str(exc)})
            continue
        item.obsidian_path = str(target)
        written.append({"id": knowledge_id, "path": str(target), "changed": changed})

    for conversation_id in payload.conversation_ids:
        conv = conv_repo.get(session, conversation_id)
        if conv is None:
            skipped.append({"id": conversation_id, "reason": "conversation not found"})
            continue
        normalized = conv_repo.to_dict(conv, with_messages=True)
        markdown = obsidian.build_raw_markdown(normalized)
        date_part = (conv.created_at or conv.updated_at).strftime("%Y-%m-%d")
        path = (
            layout.raw_dir(conv.provider_id)
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
    return {"written": written, "skipped": skipped, "vault_path": str(layout.vault_path)}


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
