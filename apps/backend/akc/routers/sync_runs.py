"""批量同步批次（需求文档 §2.2）。

批次只记录统计与失败原因；真正的逐会话抓取由扩展完成后通过
``POST /api/v1/conversations/import`` 逐条回传，保证 Raw 数据不丢。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from akc.deps import SessionDep
from akc.errors import NotFoundError
from akc.repositories import sync_run as run_repo
from akc.schemas.api import SyncRunRequest

router = APIRouter(prefix="/sync-runs", tags=["sync"])


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


@router.post("")
def create_run(payload: SyncRunRequest, session: SessionDep) -> dict[str, Any]:
    run = run_repo.create_sync_run(
        session, run_id=_new_id("srun"), provider_id=payload.provider
    )
    session.commit()
    return {
        "id": run.id,
        "provider": run.provider_id,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "targets": payload.conversation_ids,
    }


@router.post("/{run_id}/finish")
def finish_run(
    run_id: str,
    session: SessionDep,
    stats: dict[str, Any] | None = None,
    status: str = Query(default="succeeded", pattern="^(succeeded|failed|cancelled)$"),
    error: str | None = None,
) -> dict[str, object]:
    run = run_repo.get_sync_run(session, run_id)
    if run is None:
        raise NotFoundError("sync run not found", details={"id": run_id})
    run_repo.finish_sync_run(
        session, run, status=status, stats=stats or {}, error=error
    )
    session.commit()
    return {
        "id": run.id,
        "provider": run.provider_id,
        "status": run.status,
        "stats": run.stats_json,
        "error": run.error,
        "finished_at": (run.finished_at or datetime.now(timezone.utc)).isoformat(),
    }


@router.get("")
def list_runs(
    session: SessionDep, provider: str | None = Query(default=None), limit: int = Query(default=20, ge=1, le=100)
) -> dict[str, object]:
    rows = run_repo.list_sync_runs(session, provider_id=provider, limit=limit)
    return {
        "items": [
            {
                "id": row.id,
                "provider": row.provider_id,
                "status": row.status,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "stats": row.stats_json,
                "error": row.error,
            }
            for row in rows
        ],
        "count": len(rows),
    }


@router.get("/{run_id}")
def get_run(session: SessionDep, run_id: str) -> dict[str, object]:
    run = run_repo.get_sync_run(session, run_id)
    if run is None:
        raise NotFoundError("sync run not found", details={"id": run_id})
    return {
        "id": run.id,
        "provider": run.provider_id,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "stats": run.stats_json,
        "error": run.error,
    }
