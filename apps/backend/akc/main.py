"""FastAPI 应用装配。

包含：集中配置校验 → 日志 → 数据库迁移 → 任务 worker → 中间件 → 路由 → 全局错误处理。
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from akc import __version__
from akc.config import get_settings
from akc.db import init_engine
from akc.db.migrate import upgrade
from akc.deps import require_token
from akc.errors import register_exception_handlers
from akc.job_handlers import register_all_handlers
from akc.logging_setup import configure_logging, get_logger, log_event, set_request_id
from akc.routers import (
    conversations,
    health,
    jobs,
    knowledge,
    obsidian,
    providers,
    settings as settings_router,  # 避免与 get_settings() 返回的 settings 变量同名
    sync_runs,
)
from akc.services.job_service import JobWorker


def create_app() -> FastAPI:
    settings = get_settings()  # 启动即校验，配置有问题直接 fail fast
    configure_logging(settings.log_level, json_logs=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = init_engine(settings.database_url)
        executed = upgrade(engine)
        if executed:
            get_logger().info("migrations_applied", extra={"extra_fields": {"versions": executed}})

        register_all_handlers()
        worker = JobWorker(settings)
        worker.start()
        app.state.worker = worker
        log_event(
            "backend_started",
            version=__version__,
            host=settings.host,
            port=settings.port,
            env=settings.env,
        )
        try:
            yield
        finally:
            worker.stop()
            log_event("backend_stopped")

    app = FastAPI(
        title="AI Knowledge Compiler",
        version=__version__,
        description="本地知识编译服务：会话采集、Claude 编译、Obsidian 写入",
        lifespan=lifespan,
        dependencies=[],  # 令牌校验在中间件里统一处理（需读取 method）
    )

    # --- CORS：显式来源，生产禁用通配符 -----------------------------------
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["Content-Type", "X-AKC-Token"],
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = set_request_id(request.headers.get("X-Request-ID"))
        require_token(request, settings, request.headers.get("X-AKC-Token"))
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        # 安全头：本地服务同样加固
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        log_event(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response

    register_exception_handlers(app)

    api = "/api/v1"
    app.include_router(health.router, prefix=api)
    app.include_router(providers.router, prefix=api)
    app.include_router(conversations.router, prefix=api)
    app.include_router(jobs.router, prefix=api)
    app.include_router(knowledge.router, prefix=api)
    app.include_router(obsidian.router, prefix=api)
    app.include_router(settings_router.router, prefix=api)
    app.include_router(sync_runs.router, prefix=api)
    return app


app = create_app()
