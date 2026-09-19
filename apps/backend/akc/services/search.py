"""FTS5 检索（MVP 不使用向量数据库，见需求文档 §3.4）。"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from akc.services.hasher import message_text


def search_messages(
    session: Session, query: str, *, provider: str | None = None, limit: int = 20
) -> list[dict[str, object]]:
    """检索原始消息。返回 ``{message_id, conversation_id, title, snippet}``。"""
    if not query.strip():
        return []
    sql = (
        "SELECT m.id, m.conversation_id, COALESCE(c.title, ''), "
        "  snippet(messages_fts, 3, '[', ']', ' … ', 12) AS snippet "
        "FROM messages_fts "
        "JOIN messages m ON m.id = messages_fts.message_id "
        "LEFT JOIN conversations c ON c.id = m.conversation_id "
        "WHERE messages_fts MATCH :q "
    )
    params: dict[str, object] = {"q": query, "limit": limit}
    if provider:
        sql += "AND c.provider_id = :provider "
        params["provider"] = provider
    sql += "ORDER BY bm25(messages_fts) LIMIT :limit"
    rows = session.execute(text(sql), params).all()
    return [
        {"message_id": r[0], "conversation_id": r[1], "title": r[2], "snippet": r[3]}
        for r in rows
    ]


def index_preview(session: Session, conversation_id: str, limit: int = 5) -> str:
    """会话正文预览（用于侧边栏与候选检索的兜底展示）。"""
    rows = session.execute(
        text(
            "SELECT body FROM messages_fts WHERE conversation_id = :cid LIMIT :limit"
        ),
        {"cid": conversation_id, "limit": limit},
    ).all()
    return "\n".join(r[0] or "" for r in rows)


def related_knowledge_for_conversation(
    session: Session, conversation_id: str, *, limit: int = 8
) -> list[dict[str, object]]:
    """Candidate Retrieval：用会话正文检索已有知识，作为 Claude 的上下文。"""
    preview = index_preview(session, conversation_id, limit=3)
    if not preview.strip():
        return []
    keywords = _keywords(preview)
    if not keywords:
        return []
    match = " OR ".join(f'"{kw}"' for kw in keywords)
    rows = session.execute(
        text(
            "SELECT k.id, k.title, k.status, k.knowledge_type, k.summary "
            "FROM knowledge_fts "
            "JOIN knowledge k ON k.id = knowledge_fts.knowledge_id "
            "WHERE knowledge_fts MATCH :q "
            "ORDER BY bm25(knowledge_fts) LIMIT :limit"
        ),
        {"q": match, "limit": limit},
    ).all()
    return [
        {
            "id": r[0],
            "title": r[1],
            "status": r[2],
            "knowledge_type": r[3],
            "summary": r[4],
        }
        for r in rows
    ]


def _keywords(text: str, *, limit: int = 6) -> list[str]:
    """极简关键词提取（无第三方分词依赖）：按词频取头部词。"""
    tokens: list[str] = []
    for raw in text.replace("\n", " ").split(" "):
        token = "".join(ch for ch in raw if ch.isalnum() or ch.isalpha())
        if len(token) >= 2:
            tokens.append(token.lower())
    if not tokens:
        return []
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [word for word, _ in ranked[:limit]]
