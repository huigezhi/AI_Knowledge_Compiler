"""任务处理器注册。

集中注册，避免 service 之间循环依赖：handlers 只在此处互相连接。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from akc.config import Settings
from akc.errors import AppError, ErrorCode
from akc.repositories import conversation as conv_repo
from akc.services import obsidian
from akc.services.import_service import import_conversation
from akc.services.job_service import register_handler


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def _compile(session: Session, payload: dict[str, Any], settings: Settings, job_id: str) -> dict[str, Any]:
    from akc.services.compile_service import compile_conversation

    conversation_id = str(payload.get("conversation_id") or "")
    if not conversation_id:
        raise AppError(
            "payload.conversation_id is required",
            code=ErrorCode.BAD_REQUEST,
            http_status=400,
            retryable=False,
        )
    result = compile_conversation(session, conversation_id, settings=settings, job_id=job_id)

    # 自动落盘：编译成功就把产出的知识写进 Obsidian，链路到此闭环。
    # 之前止步于"知识进数据库"，用户在 Obsidian 里永远看不到，还得手动点同步。
    if settings.auto_write_obsidian and settings.vault_path:
        knowledge_ids = [str(k) for k in result.get("knowledge_ids") or []]
        if knowledge_ids:
            from akc.services import obsidian as obsidian_service

            sync = obsidian_service.sync_knowledge(session, settings, knowledge_ids)
            result["obsidian_written"] = len(sync["written"])
            result["obsidian_skipped"] = sync["skipped"]
            if sync["written"]:
                result["obsidian_paths"] = [w["path"] for w in sync["written"]]
    return result


def _write_obsidian(
    session: Session, payload: dict[str, Any], settings: Settings, job_id: str
) -> dict[str, Any]:
    if not settings.vault_path:
        raise AppError(
            "obsidian vault path is not configured",
            code=ErrorCode.OBSIDIAN_VAULT_NOT_CONFIGURED,
            http_status=400,
            retryable=False,
        )
    layout = obsidian.VaultLayout(
        vault_path=settings.vault_path,
        raw_folder=settings.vault_raw_folder,
        knowledge_folder=settings.vault_knowledge_folder,
        inbox_folder=settings.vault_inbox_folder,
    )
    kind = str(payload.get("kind") or "raw")
    entity_id = str(payload.get("conversation_id") or payload.get("knowledge_id") or "")
    if kind == "raw":
        conv = conv_repo.get(session, entity_id)
        if conv is None:
            raise AppError("conversation not found", code=ErrorCode.NOT_FOUND, http_status=404)
        markdown = obsidian.build_raw_markdown(conv_repo.to_dict(conv, with_messages=True))
        date_part = (conv.created_at or conv.updated_at).strftime("%Y-%m-%d")
        path = layout.raw_dir(conv.provider_id) / f"{obsidian.slugify(conv.title)}-{date_part}.md"
        target, changed = obsidian.write_markdown(path, markdown)
        conv.raw_payload_ref = str(target)
        session.commit()
        return {"kind": "raw", "path": str(target), "changed": changed}
    raise AppError(
        f"unsupported obsidian write kind: {kind}",
        code=ErrorCode.BAD_REQUEST,
        http_status=400,
        retryable=False,
    )


def _import_conversation(
    session: Session, payload: dict[str, Any], settings: Settings, job_id: str
) -> dict[str, Any]:
    conversation = payload.get("conversation")
    if not isinstance(conversation, dict):
        raise AppError(
            "payload.conversation is required",
            code=ErrorCode.BAD_REQUEST,
            http_status=400,
            retryable=False,
        )
    return import_conversation(
        session, conversation, settings=settings, options=dict(payload.get("options") or {})
    )


def register_all_handlers() -> None:
    register_handler("COMPILE_CONVERSATION", _compile)
    register_handler("WRITE_OBSIDIAN", _write_obsidian)
    register_handler("IMPORT_CONVERSATION", _import_conversation)
