"""sync_runs 与 compile_runs 访问。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from akc.db.models import CompileRun, SyncRun


def create_sync_run(session: Session, *, run_id: str, provider_id: str) -> SyncRun:
    run = SyncRun(id=run_id, provider_id=provider_id, status="running", stats_json={})
    session.add(run)
    session.flush()
    return run


def finish_sync_run(
    session: Session,
    run: SyncRun,
    *,
    status: str,
    stats: dict[str, Any] | None = None,
    error: str | None = None,
) -> SyncRun:
    run.status = status
    run.stats_json = dict(stats or {})
    run.error = (error or "")[:2000] or None
    run.finished_at = datetime.now(timezone.utc)
    session.flush()
    return run


def get_sync_run(session: Session, run_id: str) -> SyncRun | None:
    return session.get(SyncRun, run_id)


def list_sync_runs(session: Session, *, provider_id: str | None = None, limit: int = 20) -> list[SyncRun]:
    stmt = select(SyncRun)
    if provider_id:
        stmt = stmt.where(SyncRun.provider_id == provider_id)
    return list(session.scalars(stmt.order_by(SyncRun.started_at.desc()).limit(limit)).all())


def create_compile_run(
    session: Session,
    *,
    run_id: str,
    conversation_id: str,
    model: str,
    prompt_version: str,
    compiler_version: str,
    adapter_version: str | None = None,
    job_id: str | None = None,
    input_digest: str = "",
) -> CompileRun:
    run = CompileRun(
        id=run_id,
        conversation_id=conversation_id,
        job_id=job_id,
        model=model,
        prompt_version=prompt_version,
        compiler_version=compiler_version,
        adapter_version=adapter_version,
        status="running",
        input_digest=input_digest,
        result_json={},
    )
    session.add(run)
    session.flush()
    return run


def finish_compile_run(
    session: Session,
    run: CompileRun,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> CompileRun:
    run.status = status
    run.result_json = dict(result or {})
    run.error = (error or "")[:2000] or None
    session.flush()
    return run


def list_compile_runs(session: Session, *, conversation_id: str, limit: int = 10) -> list[CompileRun]:
    return list(
        session.scalars(
            select(CompileRun)
            .where(CompileRun.conversation_id == conversation_id)
            .order_by(CompileRun.created_at.desc())
            .limit(limit)
        ).all()
    )
