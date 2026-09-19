"""会话导入：Raw 数据落库 + 可选 Raw Markdown 写入 + 可选编译入队。

强制原则：
* Raw 数据先落库，任何后续步骤失败都**不得**回滚删除；
* Obsidian 写入失败不丢原始数据，而是转为可重试的 ``WRITE_OBSIDIAN`` 任务。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from akc.config import Settings
from akc.db.models import Conversation
from akc.logging_setup import log_event
from akc.repositories import audit, conversation as conv_repo, message as msg_repo, provider
from akc.repositories import job as job_repo
from akc.services import obsidian
from akc.services.hasher import content_hash
from akc.services.normalizer import normalize_conversation
from akc.services.provider_registry import get_spec


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def import_conversation(
    session: Session,
    payload: dict[str, Any],
    *,
    settings: Settings,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """导入一条标准化会话。返回导入结果（含幂等信息）。"""
    options = dict(options or {})
    conv = normalize_conversation(payload)

    provider_id = str(conv["provider"])
    spec = get_spec(provider_id)
    provider.ensure_provider(
        session,
        provider_id,
        display_name=spec.display_name if spec else provider_id,
        adapter_version=str(conv.get("adapter_version") or (spec.adapter_version if spec else "0.0.0")),
    )

    conversation, created = conv_repo.upsert(
        session,
        provider_id=provider_id,
        external_id=str(conv["provider_conversation_id"]),
        title=str(conv["title"]),
        content_hash=conv["content_hash"],
        url=conv.get("url"),
        model=conv.get("model"),
        schema_version=str(conv.get("schema_version") or "1.0.0"),
        adapter_version=str(conv.get("adapter_version") or "0.0.0"),
        tags=list(conv.get("tags") or []),
        conversation_id=conv.get("id"),
    )
    conv["id"] = conversation.id

    created_messages, updated_messages = msg_repo.upsert_many(
        session, conversation.id, conv["messages"]
    )

    audit.record(
        session,
        log_id=_new_id("audit"),
        event_type="conversation.imported" if created else "conversation.updated",
        entity_type="conversation",
        entity_id=conversation.id,
        detail={
            "provider": provider_id,
            "created_messages": created_messages,
            "updated_messages": updated_messages,
        },
    )

    warnings: list[str] = []
    obsidian_path: str | None = None

    if options.get("write_raw_to_obsidian"):
        try:
            obsidian_path = _write_raw(session, settings, conv, conversation)
        except Exception as exc:  # noqa: BLE001 - 写入失败不能影响 Raw 入库
            warnings.append(f"obsidian raw write deferred: {exc}")
            job_repo.enqueue(
                session,
                job_id=_new_id("job"),
                job_type="WRITE_OBSIDIAN",
                idempotency_key="|".join(
                    ["WRITE_OBSIDIAN", conversation.id, content_hash(conv["content_hash"])]
                ),
                payload={"kind": "raw", "conversation_id": conversation.id},
                max_attempts=settings.job_max_attempts,
            )

    job_id: str | None = None
    if options.get("compile") or settings.auto_compile:
        job, _ = job_repo.enqueue(
            session,
            job_id=_new_id("job"),
            job_type="COMPILE_CONVERSATION",
            idempotency_key="|".join(
                ["COMPILE_CONVERSATION", conversation.id, "extractor-v1", settings.llm_model or "-"]
            ),
            payload={"conversation_id": conversation.id},
            max_attempts=settings.job_max_attempts,
        )
        job_id = job.id

    session.commit()
    log_event(
        "conversation_imported",
        conversation_id=conversation.id,
        provider=provider_id,
        created=created,
        created_messages=created_messages,
        updated_messages=updated_messages,
    )

    return {
        "conversation_id": conversation.id,
        "created": created,
        "created_messages": created_messages,
        "updated_messages": updated_messages,
        "content_hash": conversation.content_hash,
        "obsidian_path": obsidian_path,
        "job_id": job_id,
        "warnings": warnings,
    }


def _write_raw(
    session: Session, settings: Settings, conv: dict[str, Any], conversation: Conversation
) -> str:
    if not settings.vault_path:
        raise ValueError("vault path is not configured")
    layout = obsidian.VaultLayout(
        vault_path=settings.vault_path,
        raw_folder=settings.vault_raw_folder,
        knowledge_folder=settings.vault_knowledge_folder,
        inbox_folder=settings.vault_inbox_folder,
    )
    markdown = obsidian.build_raw_markdown(conv)
    date_part = (conversation.created_at or conversation.updated_at).strftime("%Y-%m-%d")
    filename = f"{obsidian.slugify(conv['title'])}-{date_part}.md"
    path = layout.raw_dir(str(conv["provider"])) / filename
    written, _ = obsidian.write_markdown(path, markdown)
    conversation.raw_payload_ref = str(written)
    session.flush()
    return str(written)
