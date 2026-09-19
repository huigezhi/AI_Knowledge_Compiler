"""SQLAlchemy 引擎与会话。

MVP 只使用 SQLite（含 FTS5）。连接池与 WAL 均在此集中配置，业务代码不得自行创建引擎。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


class Base(DeclarativeBase):
    """声明式基类。"""


def init_engine(database_url: str, *, echo: bool = False) -> Engine:
    """创建/替换全局引擎。SQLite 启用 WAL 与外键约束。"""
    global _engine, _session_factory

    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        engine = create_engine(database_url, echo=echo, connect_args=connect_args, future=True)

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
    else:  # pragma: no cover - MVP 不支持其它数据库
        raise ValueError(f"only sqlite is supported in the MVP, got {database_url!r}")

    _engine = engine
    _session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("database engine is not initialised; call init_engine() first")
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        raise RuntimeError("session factory is not initialised; call init_engine() first")
    return _session_factory


def session_scope() -> Iterator[Session]:
    """短期会话上下文（脚本/任务使用）。HTTP 请求请走 ``deps.db_session``。"""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def resolve_sqlite_path(database_url: str, data_dir: Path) -> Path:
    raw = database_url.split("///", 1)[-1]
    path = Path(raw)
    return path if path.is_absolute() else (data_dir / path)
