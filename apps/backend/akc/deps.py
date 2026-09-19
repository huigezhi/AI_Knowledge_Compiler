"""FastAPI 依赖注入。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from akc.config import Settings, get_settings
from akc.db import get_session_factory
from akc.errors import UnauthorizedError


def settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]


def db_session() -> Iterator[Session]:
    """每个请求一个会话；异常时回滚，结束后关闭。"""
    session = get_session_factory()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(db_session)]


def require_token(
    request: Request,
    settings: SettingsDep,
    x_akc_token: Annotated[str | None, Header(alias="X-AKC-Token")] = None,
) -> None:
    """本地共享令牌校验（作为 FastAPI 依赖挂在整个应用上）。

    只监听 127.0.0.1 并不够：浏览器里的任意网页都能向 localhost 发起请求，
    因此所有写操作必须携带扩展才知道的随机 token（等价 CSRF 防护）。

    注意：**必须**作为依赖而不是 HTTP 中间件——中间件里抛出的异常无法被
    FastAPI 的全局异常处理器捕获，会退化成 500 并泄露堆栈。
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    expected = settings.auth_token
    if not expected:
        return  # 未配置令牌时保持开发态可用
    if not x_akc_token or not _safe_equal(x_akc_token, expected):
        raise UnauthorizedError("missing or invalid X-AKC-Token header")


def _safe_equal(left: str, right: str) -> bool:
    if len(left) != len(right):
        return False
    diff = 0
    for a, b in zip(left, right):
        diff |= ord(a) ^ ord(b)
    return diff == 0
