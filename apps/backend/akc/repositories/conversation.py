"""conversations 表访问（Raw 数据 —— 永不因编译失败而删除）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from akc.db.models import Conversation, Message


def get_by_external_id(
    session: Session, provider_id: str, external_id: str
) -> Conversation | None:
    stmt = select(Conversation).where(
        Conversation.provider_id == provider_id, Conversation.external_id == external_id
    )
    return session.scalars(stmt).one_or_none()


def upsert(
    session: Session,
    *,
    provider_id: str,
    external_id: str,
    title: str,
    content_hash: str,
    url: str | None = None,
    model: str | None = None,
    schema_version: str = "1.0.0",
    adapter_version: str = "0.0.0",
    raw_payload_ref: str | None = None,
    tags: list[str] | None = None,
    provider_created_at: datetime | None = None,
    provider_updated_at: datetime | None = None,
    conversation_id: str | None = None,
) -> tuple[Conversation, bool]:
    """按 (provider_id, external_id) 幂等写入。返回 ``(conversation, created)``。"""
    existing = get_by_external_id(session, provider_id, external_id)
    if existing is None:
        conv = Conversation(
            id=conversation_id or f"conv_{provider_id}_{external_id}",
            provider_id=provider_id,
            external_id=external_id,
            title=title,
            content_hash=content_hash,
            url=url,
            model=model,
            schema_version=schema_version,
            adapter_version=adapter_version,
            raw_payload_ref=raw_payload_ref,
            tags_json=list(tags or []),
            provider_created_at=provider_created_at,
            provider_updated_at=provider_updated_at,
        )
        session.add(conv)
        session.flush()
        return conv, True

    existing.title = title or existing.title
    existing.content_hash = content_hash
    if url:
        existing.url = url
    if model:
        existing.model = model
    existing.schema_version = schema_version
    existing.adapter_version = adapter_version
    if raw_payload_ref:
        existing.raw_payload_ref = raw_payload_ref
    if tags is not None:
        existing.tags_json = list(tags)
    if provider_created_at:
        existing.provider_created_at = provider_created_at
    if provider_updated_at:
        existing.provider_updated_at = provider_updated_at
    session.flush()
    return existing, False


def get(session: Session, conversation_id: str) -> Conversation | None:
    return session.get(Conversation, conversation_id)


def list_conversations(
    session: Session,
    *,
    provider_id: str | None = None,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Conversation], int]:
    stmt = select(Conversation)
    count_stmt = select(func.count()).select_from(Conversation)
    if provider_id:
        stmt = stmt.where(Conversation.provider_id == provider_id)
        count_stmt = count_stmt.where(Conversation.provider_id == provider_id)
    if query:
        like = f"%{query}%"
        stmt = stmt.where(Conversation.title.like(like))
        count_stmt = count_stmt.where(Conversation.title.like(like))
    total = int(session.scalar(count_stmt) or 0)
    rows = list(
        session.scalars(
            stmt.order_by(Conversation.updated_at.desc()).limit(limit).offset(offset)
        ).all()
    )
    return rows, total


def mark_compiled(session: Session, conversation_id: str, when: datetime) -> None:
    conv = session.get(Conversation, conversation_id)
    if conv is not None:
        conv.compiled_at = when


def to_dict(conv: Conversation, *, with_messages: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": conv.id,
        "provider": conv.provider_id,
        "provider_conversation_id": conv.external_id,
        "title": conv.title,
        "url": conv.url,
        "model": conv.model,
        "content_hash": conv.content_hash,
        "schema_version": conv.schema_version,
        "adapter_version": conv.adapter_version,
        "tags": list(conv.tags_json or []),
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
        "compiled_at": conv.compiled_at.isoformat() if conv.compiled_at else None,
        "message_count": len(conv.messages) if conv.messages is not None else 0,
    }
    if with_messages:
        payload["messages"] = [
            {
                "id": m.id,
                "role": m.role,
                "sequence": m.sequence,
                "content": m.content_json,
                "content_hash": m.content_hash,
                "model": m.model,
                "created_at": m.provider_created_at.isoformat() if m.provider_created_at else None,
            }
            for m in sorted(conv.messages or [], key=lambda m: m.sequence)
        ]
    return payload


__all__ = [
    "Conversation",
    "Message",
    "get",
    "get_by_external_id",
    "list_conversations",
    "mark_compiled",
    "to_dict",
    "upsert",
]
