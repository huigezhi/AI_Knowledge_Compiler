"""任务队列端点。"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from akc.deps import SessionDep, SettingsDep
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
    key_parts = (conv_id, "extractor-v1", settings.claude_model or "-")
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
