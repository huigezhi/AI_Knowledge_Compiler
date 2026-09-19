"""pytest 共享夹具。

每个测试使用独立的临时目录 + 独立 SQLite 文件，互不影响。
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# 环境变量必须在导入 akc.config 之前设定，否则 Settings 校验会失败。
os.environ.setdefault("AKC_ENV", "test")
os.environ.setdefault("AKC_DATA_DIR", str(Path(tempfile.mkdtemp(prefix="akc-conftest-"))))
os.environ.setdefault(
    "AKC_DATABASE_URL",
    f"sqlite+pysqlite:///{Path(os.environ['AKC_DATA_DIR']).as_posix()}/akc.db",
)

from akc.config import Settings, get_settings  # noqa: E402
from akc.db import get_engine, get_session_factory, init_engine  # noqa: E402
from akc.db.migrate import upgrade  # noqa: E402
from akc.main import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    monkeypatch.setenv("AKC_ENV", "test")
    monkeypatch.setenv("AKC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AKC_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path.as_posix()}/akc.db")
    monkeypatch.setenv("AKC_LOG_JSON", "false")
    monkeypatch.setenv("AKC_LOG_LEVEL", "WARNING")
    # 固定令牌，便于验证「写请求必须带 X-AKC-Token」的拦截行为
    monkeypatch.setenv("AKC_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("AKC_JOB_BACKOFF_SECONDS", "0,0,0")  # 测试中重试立即到期
    monkeypatch.delenv("AKC_VAULT_PATH", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    init_engine(settings.database_url)
    upgrade(get_engine())
    yield settings
    get_settings.cache_clear()


@pytest.fixture
def settings(isolated_env: Settings) -> Settings:
    return isolated_env


@pytest.fixture
def session() -> Iterator[Session]:
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """已携带本地令牌的客户端（模拟扩展的写请求）。"""
    with TestClient(create_app()) as test_client:
        if settings.auth_token:
            test_client.headers["X-AKC-Token"] = settings.auth_token
        yield test_client


@pytest.fixture
def anonymous_client() -> Iterator[TestClient]:
    """不带令牌的客户端（模拟浏览器里其它网页伪造的本地请求）。"""
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def vault(tmp_path: Path, settings: Settings) -> Path:
    path = tmp_path / "vault"
    path.mkdir(parents=True, exist_ok=True)
    settings.vault_path = path
    return path
