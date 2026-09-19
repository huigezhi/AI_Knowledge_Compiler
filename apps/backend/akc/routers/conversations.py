"""会话导入与查询。"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from akc.deps import SessionDep, SettingsDep
from akc.repositories import conversation as conv_repo
from akc.schemas.api import ImportRequest, ImportResponse
from akc.services.import_service import import_conversation

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("/import", response_model=ImportResponse)
def import_one(
    payload: ImportRequest, session: SessionDep, settings: SettingsDep
) -> ImportResponse:
    result = import_conversation(
        session,
        payload.conversation,
        settings=settings,
        options=payload.options.model_dump(),
    )
    return ImportResponse(**result)


@router.get("")
def list_conversations(
    session: SessionDep,
    provider: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    rows, total = conv_repo.list_conversations(
        session, provider_id=provider, query=q, limit=limit, offset=offset
    )
    return {
        "items": [conv_repo.to_dict(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{conversation_id}")
def get_conversation(session: SessionDep, conversation_id: str) -> dict[str, object]:
    conv = conv_repo.get(session, conversation_id)
    if conv is None:
        from akc.errors import NotFoundError

        raise NotFoundError("conversation not found", details={"id": conversation_id})
    return conv_repo.to_dict(conv, with_messages=True)


@router.get("/{conversation_id}/export")
def export_conversation(
    session: SessionDep,
    conversation_id: str,
    fmt: str = Query(default="markdown", pattern="^(markdown|json)$"),
) -> dict[str, object]:
    conv = conv_repo.get(session, conversation_id)
    if conv is None:
        from akc.errors import NotFoundError

        raise NotFoundError("conversation not found", details={"id": conversation_id})
    from akc.services.export import export_conversation as _export

    normalized = _normalized_conversation(conv)
    content, media_type = _export(normalized, fmt=fmt)
    return {"conversation_id": conversation_id, "format": fmt, "media_type": media_type, "content": content}


def _normalized_conversation(conv) -> dict[str, object]:  # noqa: ANN001 - 内部辅助
    from akc.repositories import conversation as repo

    return repo.to_dict(conv, with_messages=True)
