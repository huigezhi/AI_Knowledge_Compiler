"""知识检索、审核与合并。"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from akc.deps import SessionDep
from akc.errors import AppError, ErrorCode, NotFoundError
from akc.repositories import knowledge as kn_repo
from akc.schemas.api import MergeRequest, ReclassifyRequest, ReviewRequest
from akc.services import reclassify_service, review_service

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

_ACTION_TO_STATUS = {
    "verify": "verified",
    "reject": "rejected",
    "archive": "archived",
    "review": "review",
    "delete": "deleted",
    "restore": "candidate",  # 误删恢复：deleted -> candidate
}


@router.get("")
def list_knowledge(
    session: SessionDep,
    status: str | None = Query(default=None),
    knowledge_type: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    q: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    rows, total = kn_repo.list_knowledge(
        session,
        status=status,
        knowledge_type=knowledge_type,
        domain=domain,
        query=q,
        include_inactive=include_inactive,
        limit=limit,
        offset=offset,
    )
    items = [
        kn_repo.to_dict(
            row,
            sources=[link.message_id for link in kn_repo.sources_for(session, row.id)],
        )
        for row in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/search")
def search(session: SessionDep, q: str = Query(min_length=1), limit: int = Query(default=20, ge=1, le=100)) -> dict[str, object]:
    rows = kn_repo.search_fts(session, q, limit=limit)
    items = [
        kn_repo.to_dict(
            row, sources=[link.message_id for link in kn_repo.sources_for(session, row.id)]
        )
        for row in rows
    ]
    return {"items": items, "query": q, "count": len(items)}


@router.post("/reclassify")
def reclassify(
    payload: ReclassifyRequest, session: SessionDep
) -> dict[str, object]:
    """重新分类与归并：dry_run 返回预览，确认后 dry_run=False 执行。"""
    plan_result = reclassify_service.plan(
        session, domain=payload.domain, force=payload.force
    )
    if payload.dry_run:
        return {**plan_result, "dry_run": True}
    applied = reclassify_service.apply(session, plan_result)
    return {**applied, "dry_run": False}


@router.get("/{knowledge_id}")
def get_knowledge(session: SessionDep, knowledge_id: str) -> dict[str, object]:
    item = kn_repo.get(session, knowledge_id)
    if item is None:
        raise NotFoundError("knowledge not found", details={"id": knowledge_id})
    return kn_repo.to_dict(
        item, sources=[link.message_id for link in kn_repo.sources_for(session, knowledge_id)]
    )


@router.post("/{knowledge_id}/review")
def review_knowledge(
    payload: ReviewRequest, session: SessionDep, knowledge_id: str
) -> dict[str, object]:
    status = _ACTION_TO_STATUS.get(payload.action.lower())
    if status is None:
        raise AppError(
            f"unsupported review action: {payload.action}",
            code=ErrorCode.BAD_REQUEST,
            http_status=400,
            details={"allowed": sorted(_ACTION_TO_STATUS)},
        )
    return review_service.set_status(session, knowledge_id, status, reason=payload.reason)


@router.post("/{knowledge_id}/merge")
def merge_knowledge(
    payload: MergeRequest, session: SessionDep, knowledge_id: str
) -> dict[str, object]:
    return review_service.merge_knowledge(
        session, knowledge_id, payload.target_knowledge_id, reason=payload.reason
    )


@router.post("/{knowledge_id}/unmerge")
def unmerge_knowledge(session: SessionDep, knowledge_id: str) -> dict[str, object]:
    return review_service.unmerge_knowledge(session, knowledge_id)
