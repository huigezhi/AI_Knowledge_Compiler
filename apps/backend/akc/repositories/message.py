"""messages 表访问。

去重语义（需求文档 §5.3）：
* ``(conversation_id, external_id)`` 唯一；
* 同一 external_id 且 ``content_hash`` 未变 → 跳过（不产生重复记录）；
* 内容变化 → 更新，**但不删除历史消息**。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from akc.db.models import Message


def upsert_many(
    session: Session,
    conversation_id: str,
    messages: list[dict[str, Any]],
) -> tuple[int, int]:
    """批量幂等写入。返回 ``(created, updated)`` 计数。"""
    stored = list(
        session.scalars(select(Message).where(Message.conversation_id == conversation_id)).all()
    )
    existing_by_external = {m.external_id: m for m in stored if m.external_id}
    existing_by_id = {m.id: m for m in stored}
    created = 0
    updated = 0

    for msg in messages:
        external_id = msg.get("provider_message_id") or msg.get("id")
        content_hash = msg["content_hash"]
        # 优先按 external_id 匹配；external_id 变化（例如平台改了 id 策略）时按主键兜底，
        # 避免把同一条消息重复插入。
        current = existing_by_external.get(external_id) or existing_by_id.get(msg["id"])

        if current is None:
            session.add(
                Message(
                    id=msg["id"],
                    conversation_id=conversation_id,
                    external_id=external_id,
                    role=msg["role"],
                    sequence=msg["sequence"],
                    content_json=msg["content"],
                    content_hash=content_hash,
                    model=msg.get("model"),
                    parent_message_id=msg.get("parent_message_id"),
                    provider_created_at=_parse_dt(msg.get("created_at")),
                    metadata_json=dict(msg.get("metadata") or {}),
                )
            )
            created += 1
            continue

        if current.content_hash == content_hash:
            continue  # 幂等：内容未变化

        current.content_json = msg["content"]
        current.content_hash = content_hash
        current.sequence = msg["sequence"]
        current.role = msg["role"]
        current.external_id = external_id
        if msg.get("model"):
            current.model = msg["model"]
        if msg.get("metadata"):
            current.metadata_json = dict(msg["metadata"])
        updated += 1

    session.flush()
    return created, updated


def list_messages(session: Session, conversation_id: str) -> list[Message]:
    return list(
        session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.sequence)
        ).all()
    )


def get(session: Session, message_id: str) -> Message | None:
    return session.get(Message, message_id)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
