"""健康检查端点。"""

from __future__ import annotations

from fastapi import APIRouter

from akc import __version__
from akc.config import COMPILER_VERSION, SCHEMA_VERSION, Settings
from akc.deps import SettingsDep
from akc.errors import AppError, ErrorCode

router = APIRouter(tags=["health"])


@router.get("/health")
def health(settings: SettingsDep) -> dict[str, object]:
    return {
        "status": "ok",
        "service": "akc-backend",
        "version": __version__,
        "compiler_version": COMPILER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "env": settings.env,
    }


@router.get("/ready")
def ready(settings: SettingsDep) -> dict[str, object]:
    """就绪探针：校验关键配置是否可用（数据库由迁移保证，此处只做轻量判断）。"""
    problems: list[str] = []
    if settings.claude_enabled and not (settings.claude_api_key and settings.claude_model):
        problems.append("claude compiler enabled but api key/model missing")
    if not settings.data_dir.exists():
        problems.append("data_dir does not exist")
    if problems:
        raise AppError(
            "service is not ready",
            code=ErrorCode.INTERNAL,
            http_status=503,
            details={"problems": problems},
        )
    return {"status": "ready", "checks": {"config": "ok"}}
