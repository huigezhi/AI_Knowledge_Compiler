"""知识审核与合并（需求文档 §8.3）。

状态机：candidate → review → verified | rejected；verified ⇄ merged；verified → archived。
**任何自动合并都必须可撤销**；verified 不被低置信度 candidate 静默覆盖。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from akc.errors import AppError, ConflictError, NotFoundError
from akc.repositories import audit, knowledge as kn_repo

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "candidate": {"review", "verified", "rejected", "archived", "deleted"},
    "review": {"verified", "rejected", "candidate", "archived", "deleted"},
    "verified": {"archived", "merged", "review", "deleted"},
    "rejected": {"candidate", "archived", "deleted"},
    "merged": {"verified"},  # 撤销合并
    "archived": {"verified", "candidate", "deleted"},
    "deleted": {"candidate"},  # 误删可恢复
}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def set_status(session: Session, knowledge_id: str, status: str, *, reason: str = "") -> dict[str, Any]:
    item = kn_repo.get(session, knowledge_id)
    if item is None:
        raise NotFoundError("knowledge not found", details={"id": knowledge_id})
    status = status.lower()
    if status != item.status:
        allowed = _ALLOWED_TRANSITIONS.get(item.status, set())
        if status not in allowed:
            raise ConflictError(
                f"illegal knowledge transition: {item.status} -> {status}",
                details={"allowed": sorted(allowed)},
            )
        kn_repo.set_status(session, item, status)
        audit.record(
            session,
            log_id=_new_id("audit"),
            event_type=f"knowledge.{status}",
            entity_type="knowledge",
            entity_id=knowledge_id,
            detail={"from": item.status, "to": status, "reason": reason},
        )
        session.commit()
    return kn_repo.to_dict(item, sources=_source_ids(session, knowledge_id))


def merge_knowledge(
    session: Session, source_id: str, target_id: str, *, reason: str = ""
) -> dict[str, Any]:
    """把 ``source_id`` 合并进 ``target_id``。

    * target 保留为唯一主知识；
    * source 标记为 ``merged`` 并记录 ``superseded_by``（**可撤销**）；
    * source 的溯源关系迁移到 target，保证知识不会失联。
    """
    if source_id == target_id:
        raise AppError("cannot merge a knowledge item into itself", code=AppError.code.__class__("BAD_REQUEST"))  # type: ignore[attr-defined]

    source = kn_repo.get(session, source_id)
    target = kn_repo.get(session, target_id)
    if source is None or target is None:
        raise NotFoundError("knowledge not found")

    for link in kn_repo.sources_for(session, source_id):
        kn_repo.link_sources(
            session,
            knowledge_id=target_id,
            message_ids=[link.message_id],
            conversation_id=link.conversation_id,
            relation_type=link.relation_type,
        )
    kn_repo.link_knowledge(
        session, knowledge_id=target_id, related_knowledge_id=source_id, link_type="merged_from"
    )
    kn_repo.set_status(session, source, "merged", superseded_by=target_id)
    audit.record(
        session,
        log_id=_new_id("audit"),
        event_type="knowledge.merged",
        entity_type="knowledge",
        entity_id=source_id,
        detail={"into": target_id, "reason": reason},
    )
    session.commit()
    return {
        "source": kn_repo.to_dict(source),
        "target": kn_repo.to_dict(target, sources=_source_ids(session, target_id)),
    }


def unmerge_knowledge(session: Session, knowledge_id: str) -> dict[str, Any]:
    """撤销合并（destructive action 的可逆保障）。"""
    item = kn_repo.get(session, knowledge_id)
    if item is None:
        raise NotFoundError("knowledge not found")
    if item.status != "merged":
        raise ConflictError("only merged knowledge can be unmerged")
    kn_repo.set_status(session, item, "verified", superseded_by=None)
    audit.record(
        session,
        log_id=_new_id("audit"),
        event_type="knowledge.unmerged",
        entity_type="knowledge",
        entity_id=knowledge_id,
    )
    session.commit()
    return kn_repo.to_dict(item, sources=_source_ids(session, knowledge_id))


def _source_ids(session: Session, knowledge_id: str) -> list[str]:
    return [link.message_id for link in kn_repo.sources_for(session, knowledge_id)]
