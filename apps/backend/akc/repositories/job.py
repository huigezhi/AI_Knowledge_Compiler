"""jobs 表访问 —— SQLite 任务队列（需求文档 §15）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from akc.db.models import Job

_TERMINAL = ("succeeded", "failed", "cancelled")


def enqueue(
    session: Session,
    *,
    job_id: str,
    job_type: str,
    idempotency_key: str,
    payload: dict[str, Any],
    max_attempts: int = 3,
    run_at: datetime | None = None,
) -> tuple[Job, bool]:
    """按幂等键入队。若已存在同名幂等键且尚未终态，则返回既有 job。"""
    existing = session.scalars(
        select(Job).where(Job.idempotency_key == idempotency_key)
    ).one_or_none()
    if existing is not None:
        return existing, False

    job = Job(
        id=job_id,
        job_type=job_type,
        idempotency_key=idempotency_key,
        payload_json=dict(payload),
        status="pending",
        attempts=0,
        max_attempts=max_attempts,
        next_run_at=run_at or datetime.now(timezone.utc),
    )
    session.add(job)
    session.flush()
    return job, True


def get(session: Session, job_id: str) -> Job | None:
    return session.get(Job, job_id)


def claim_next(session: Session, *, job_types: list[str] | None = None) -> Job | None:
    """取出下一个到期任务并标记为 running（单消费者，SQLite 下按事务串行）。"""
    stmt = (
        select(Job)
        .where(Job.status == "pending", Job.next_run_at <= datetime.now(timezone.utc))
        .order_by(Job.next_run_at)
        .limit(1)
    )
    if job_types:
        stmt = select(Job).where(
            Job.status == "pending",
            Job.next_run_at <= datetime.now(timezone.utc),
            Job.job_type.in_(job_types),
        ).order_by(Job.next_run_at).limit(1)
    job = session.scalars(stmt).one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    session.flush()
    return job


def mark_succeeded(session: Session, job: Job, result: dict[str, Any] | None = None) -> Job:
    job.status = "succeeded"
    job.result_json = dict(result or {})
    job.error = None
    job.error_code = None
    job.finished_at = datetime.now(timezone.utc)
    job.stage = None
    session.flush()
    return job


def mark_failed(
    session: Session,
    job: Job,
    *,
    error: str,
    error_code: str | None = None,
    retryable: bool,
    backoff_seconds: list[int],
) -> Job:
    """失败处理：可重试则按指数退避重排；超过最大次数进入 failed（死信）。"""
    can_retry = retryable and job.attempts < job.max_attempts
    if can_retry:
        index = min(job.attempts - 1, len(backoff_seconds) - 1)
        delay = backoff_seconds[max(index, 0)]
        job.status = "pending"
        job.next_run_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
    else:
        job.status = "failed"
        job.finished_at = datetime.now(timezone.utc)
    job.error = error[:2000]
    job.error_code = error_code
    job.stage = None
    session.flush()
    return job


def set_stage(session: Session, job: Job, stage: str) -> None:
    job.stage = stage
    session.flush()


def cancel(session: Session, job: Job) -> Job:
    if job.status in _TERMINAL:
        return job
    job.status = "cancelled"
    job.finished_at = datetime.now(timezone.utc)
    session.flush()
    return job


def list_jobs(
    session: Session, *, status: str | None = None, limit: int = 50
) -> list[Job]:
    stmt = select(Job)
    if status:
        stmt = stmt.where(Job.status == status)
    return list(
        session.scalars(stmt.order_by(Job.created_at.desc()).limit(limit)).all()
    )


def to_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "stage": job.stage,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "idempotency_key": job.idempotency_key,
        "payload": dict(job.payload_json or {}),
        "result": dict(job.result_json or {}),
        "error": job.error,
        "error_code": job.error_code,
        "next_run_at": job.next_run_at.isoformat() if job.next_run_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }
