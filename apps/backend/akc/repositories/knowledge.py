"""knowledge / knowledge_sources / knowledge_links 访问。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from akc.db.models import Knowledge, KnowledgeLink, KnowledgeSource
from akc.services.hasher import content_hash

_ACTIVE_STATUSES = ("verified", "candidate", "review", "merged")


def create(
    session: Session,
    *,
    knowledge_id: str,
    slug: str,
    title: str,
    knowledge_type: str = "fact",
    domain: str = "其他",
    summary: str = "",
    markdown: str = "",
    confidence: float = 0.5,
    needs_verification: bool = True,
    topics: list[str] | None = None,
    entities: list[str] | None = None,
    status: str = "candidate",
    prompt_version: str | None = None,
    model: str | None = None,
) -> Knowledge:
    item = Knowledge(
        id=knowledge_id,
        slug=slug,
        title=title,
        knowledge_type=knowledge_type,
        domain=domain,
        status=status,
        summary=summary,
        markdown=markdown,
        content_hash=content_hash(markdown or summary),
        confidence=confidence,
        needs_verification=1 if needs_verification else 0,
        topics_json=list(topics or []),
        entities_json=list(entities or []),
        prompt_version=prompt_version,
        model=model,
    )
    session.add(item)
    session.flush()
    return item


def get(session: Session, knowledge_id: str) -> Knowledge | None:
    return session.get(Knowledge, knowledge_id)


def update_content(
    session: Session,
    item: Knowledge,
    *,
    markdown: str | None = None,
    summary: str | None = None,
    title: str | None = None,
) -> Knowledge:
    """更新内容并递增 version（支持回滚）。"""
    if title is not None:
        item.title = title
    if summary is not None:
        item.summary = summary
    if markdown is not None:
        item.markdown = markdown
    item.content_hash = content_hash(item.markdown or item.summary)
    item.version += 1
    session.flush()
    return item


def set_status(
    session: Session, item: Knowledge, status: str, *, superseded_by: str | None = None
) -> Knowledge:
    item.status = status
    if superseded_by is not None:
        item.superseded_by = superseded_by
    session.flush()
    return item


def list_knowledge(
    session: Session,
    *,
    status: str | None = None,
    knowledge_type: str | None = None,
    include_inactive: bool = False,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Knowledge], int]:
    stmt = select(Knowledge)
    count_stmt = select(func.count()).select_from(Knowledge)
    if status:
        stmt = stmt.where(Knowledge.status == status)
        count_stmt = count_stmt.where(Knowledge.status == status)
    elif not include_inactive:
        stmt = stmt.where(Knowledge.status.in_(_ACTIVE_STATUSES))
        count_stmt = count_stmt.where(Knowledge.status.in_(_ACTIVE_STATUSES))
    if knowledge_type:
        stmt = stmt.where(Knowledge.knowledge_type == knowledge_type)
        count_stmt = count_stmt.where(Knowledge.knowledge_type == knowledge_type)
    if query:
        like = f"%{query}%"
        clause = Knowledge.title.like(like) | Knowledge.summary.like(like)
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    total = int(session.scalar(count_stmt) or 0)
    rows = list(
        session.scalars(stmt.order_by(Knowledge.updated_at.desc()).limit(limit).offset(offset)).all()
    )
    return rows, total


def search_fts(session: Session, query: str, *, limit: int = 20) -> list[Knowledge]:
    """FTS5 检索（P1 可叠加 embedding；MVP 只用 FTS）。"""
    if not query.strip():
        return []
    rows = session.execute(
        text(
            "SELECT knowledge_id FROM knowledge_fts WHERE knowledge_fts MATCH :q "
            "ORDER BY bm25(knowledge_fts) LIMIT :limit"
        ),
        {"q": query, "limit": limit},
    ).all()
    ids = [r[0] for r in rows]
    if not ids:
        return []
    return list(session.scalars(select(Knowledge).where(Knowledge.id.in_(ids))).all())


def link_sources(
    session: Session,
    *,
    knowledge_id: str,
    message_ids: list[str],
    conversation_id: str,
    relation_type: str = "supports",
) -> int:
    """写入溯源关系（幂等）。返回新增条数。"""
    existing = {
        (row.message_id, row.relation_type)
        for row in session.scalars(
            select(KnowledgeSource).where(KnowledgeSource.knowledge_id == knowledge_id)
        ).all()
    }
    added = 0
    for message_id in message_ids:
        key = (message_id, relation_type)
        if key in existing:
            continue
        session.add(
            KnowledgeSource(
                id=f"ksrc_{knowledge_id}_{message_id}_{relation_type}"[:120],
                knowledge_id=knowledge_id,
                message_id=message_id,
                conversation_id=conversation_id,
                relation_type=relation_type,
            )
        )
        existing.add(key)
        added += 1
    session.flush()
    return added


def sources_for(session: Session, knowledge_id: str) -> list[KnowledgeSource]:
    return list(
        session.scalars(
            select(KnowledgeSource).where(KnowledgeSource.knowledge_id == knowledge_id)
        ).all()
    )


def link_knowledge(
    session: Session,
    *,
    knowledge_id: str,
    related_knowledge_id: str,
    link_type: str = "related",
    confidence: float = 0.5,
) -> None:
    if knowledge_id == related_knowledge_id:
        return
    exists = session.scalars(
        select(KnowledgeLink).where(
            KnowledgeLink.knowledge_id == knowledge_id,
            KnowledgeLink.related_knowledge_id == related_knowledge_id,
            KnowledgeLink.link_type == link_type,
        )
    ).first()
    if exists:
        return
    session.add(
        KnowledgeLink(
            id=f"klink_{knowledge_id}_{related_knowledge_id}_{link_type}"[:160],
            knowledge_id=knowledge_id,
            related_knowledge_id=related_knowledge_id,
            link_type=link_type,
            confidence=confidence,
        )
    )
    session.flush()


def to_dict(item: Knowledge, *, sources: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": item.id,
        "slug": item.slug,
        "title": item.title,
        "status": item.status,
        "knowledge_type": item.knowledge_type,
        "summary": item.summary,
        "markdown": item.markdown,
        "confidence": item.confidence,
        "needs_verification": bool(item.needs_verification),
        "topics": list(item.topics_json or []),
        "entities": list(item.entities_json or []),
        "version": item.version,
        "content_hash": item.content_hash,
        "superseded_by": item.superseded_by,
        "obsidian_path": item.obsidian_path,
        "prompt_version": item.prompt_version,
        "model": item.model,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "source_message_ids": sources or [],
    }
