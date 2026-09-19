"""Provider 状态查询。"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy.orm import Session

from akc.deps import SessionDep
from akc.repositories import provider as provider_repo
from akc.services.provider_registry import all_specs, to_dict

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("")
def list_providers(session: SessionDep) -> dict[str, object]:
    rows = {row.id: row for row in provider_repo.list_providers(session)}
    items = []
    for spec in all_specs():
        stored = rows.get(spec.id)
        items.append(
            to_dict(
                spec,
                enabled=bool(stored.enabled) if stored else True,
            )
            | {
                "adapter_version": (stored.adapter_version if stored else spec.adapter_version),
                "known": stored is not None,
            }
        )
    return {"items": items, "count": len(items)}
