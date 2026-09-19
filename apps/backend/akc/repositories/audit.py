"""audit_logs 访问 —— 所有关键状态变更都留痕，保证可追溯。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from akc.db.models import AuditLog


def record(
    session: Session,
    *,
    log_id: str,
    event_type: str,
    entity_type: str = "",
    entity_id: str = "",
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        id=log_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        detail_json=dict(detail or {}),
    )
    session.add(entry)
    session.flush()
    return entry


def list_audit(
    session: Session,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 100,
) -> list[AuditLog]:
    stmt = select(AuditLog)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    return list(session.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(limit)).all())
