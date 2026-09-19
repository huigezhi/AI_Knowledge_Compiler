"""任务队列端点。"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from akc.deps import SessionDep, SettingsDep
from akc.compiler.prompts import EXTRACTOR_PROMPT_VERSION
from akc.errors import NotFoundError
from akc.repositories import job as job_repo
from akc.schemas.api import CompileRequest
from akc.services.job_service import enqueue_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    session: SessionDep,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, object]:
    rows = job_repo.list_jobs(session, status=status, limit=limit)
    return {"items": [job_repo.to_dict(row) for row in rows], "count": len(rows)}


@router.post("/compile")
def create_compile_job(
    payload: CompileRequest, session: SessionDep, settings: SettingsDep
) -> dict[str, object]:
    conv_id = payload.conversation_id
    if not conv_id:
        from akc.errors import AppError, ErrorCode

        raise AppError("conversation_id is required", code=ErrorCode.BAD_REQUEST, http_status=400)
    # 键必须与 import_service 的自动编译一致（含内容哈希）：
    # 内容变化 -> 新键 -> 重新编译；内容不变 -> 幂等返回旧结果
    from akc.repositories import conversation as conv_repo

    conv = conv_repo.get(session, conv_id)
    content_hash = str(conv.content_hash or "") if conv is not None else ""
    key_parts = (
        conv_id,
        EXTRACTOR_PROMPT_VERSION,
        settings.llm_model or "-",
        content_hash,
    )
    if payload.idempotency_key:
        key_parts = key_parts + (payload.idempotency_key,)
    return enqueue_job(
        session,
        job_type="COMPILE_CONVERSATION",
        parts=key_parts,
        payload={"conversation_id": conv_id},
        settings=settings,
    )


@router.get("/{job_id}")
def get_job(session: SessionDep, job_id: str) -> dict[str, object]:
    job = job_repo.get(session, job_id)
    if job is None:
        raise NotFoundError("job not found", details={"id": job_id})
    return job_repo.to_dict(job)


@router.post("/{job_id}/cancel")
def cancel_job(session: SessionDep, job_id: str) -> dict[str, object]:
    job = job_repo.get(session, job_id)
    if job is None:
        raise NotFoundError("job not found", details={"id": job_id})
    job_repo.cancel(session, job)
    session.commit()
    return job_repo.to_dict(job)
