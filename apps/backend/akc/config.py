"""集中配置。

规则：
* 所有配置来自环境变量（可选 .env 文件），**启动时集中校验、快速失败**；
* 密钥只存在于环境变量 / 本地文件中，绝不写入代码库；
* 模型 ID 一律配置注入，业务代码不得硬编码模型名。

变量前缀统一为 ``AKC_``，与仓库根目录 ``.env.example`` 一一对应。
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# 与 packages/schema 中的 SCHEMA_VERSION 保持一致，变更时必须同步 + 迁移。
SCHEMA_VERSION = "1.0.0"
COMPILER_VERSION = "0.1.0"

_VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class Settings(BaseSettings):
    """运行环境配置。"""

    model_config = SettingsConfigDict(
        env_prefix="AKC_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- service -----------------------------------------------------------
    env: Literal["development", "test", "production"] = "development"
    host: str = "127.0.0.1"
    port: int = 38127
    log_level: str = "INFO"
    log_json: bool = True

    # --- storage -----------------------------------------------------------
    data_dir: Path = Field(default=Path("./data"))
    database_url: str = "sqlite+pysqlite:///./data/akc.db"

    # --- security ----------------------------------------------------------
    auth_token: str | None = None
    # NoDecode：环境变量使用逗号分隔写法（见 .env.example），由下面的校验器解析。
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- obsidian ----------------------------------------------------------
    vault_path: Path | None = None
    vault_raw_folder: str = "01_Raw"
    vault_knowledge_folder: str = "03_Knowledge"
    vault_inbox_folder: str = "02_Inbox"

    # --- claude / compiler -------------------------------------------------
    claude_enabled: bool = False
    claude_model: str | None = None
    claude_api_key: str | None = None
    claude_base_url: str = "https://api.anthropic.com"
    claude_max_context_tokens: int = 50_000
    claude_timeout_seconds: float = 120.0

    # --- compile policy ----------------------------------------------------
    auto_compile: bool = False
    auto_merge_verified: bool = False
    require_review_for_conflicts: bool = True

    # --- job queue ---------------------------------------------------------
    job_poll_interval_seconds: float = 2.0
    job_max_attempts: int = 3
    job_backoff_seconds: Annotated[list[int], NoDecode] = Field(default_factory=lambda: [2, 5, 15])

    # ------------------------------------------------------------------ 校验
    @field_validator("log_level")
    @classmethod
    def _check_log_level(cls, v: str) -> str:
        level = v.upper()
        if level not in _VALID_LOG_LEVELS:
            raise ValueError(f"AKC_LOG_LEVEL must be one of {_VALID_LOG_LEVELS}, got {v!r}")
        return level

    @field_validator("port")
    @classmethod
    def _check_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError(f"AKC_PORT out of range: {v}")
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return list(v)  # type: ignore[arg-type]

    @field_validator("job_backoff_seconds", mode="before")
    @classmethod
    def _split_backoff(cls, v: object) -> list[int]:
        if isinstance(v, str):
            return [int(item) for item in v.split(",") if item.strip()]
        return list(v)  # type: ignore[arg-type]

    @model_validator(mode="after")
    def _check_compiler(self) -> Settings:
        if self.claude_enabled and not (self.claude_api_key and self.claude_model):
            raise ValueError(
                "AKC_CLAUDE_ENABLED=true requires both AKC_CLAUDE_API_KEY and AKC_CLAUDE_MODEL"
            )
        if self.claude_max_context_tokens < 1_000:
            raise ValueError("AKC_CLAUDE_MAX_CONTEXT_TOKENS must be >= 1000")
        if self.job_max_attempts < 1:
            raise ValueError("AKC_JOB_MAX_ATTEMPTS must be >= 1")
        if not self.job_backoff_seconds:
            raise ValueError("AKC_JOB_BACKOFF_SECONDS must not be empty")
        # Local-first：生产环境只允许回环监听，避免把本地服务暴露到局域网。
        if self.env == "production" and self.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("AKC_HOST must be a loopback address when AKC_ENV=production")
        return self

    # ------------------------------------------------------------------ 派生
    @property
    def database_path(self) -> Path:
        """从 SQLAlchemy URL 推导 SQLite 文件路径（仅支持 sqlite 驱动）。"""
        prefix = "sqlite"
        if not self.database_url.startswith(prefix):
            raise ValueError(f"only sqlite is supported in the MVP, got {self.database_url!r}")
        raw = self.database_url.split("///", 1)[-1]
        path = Path(raw)
        return path if path.is_absolute() else (self.data_dir / path)

    def ensure_data_dir(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir

    def ensure_auth_token(self) -> str:
        """返回本地共享令牌；未配置时生成并持久化到 data_dir。

        扩展的每个写请求都必须携带 ``X-AKC-Token``，用于阻止其它网页伪造本地请求。
        """
        if self.auth_token:
            return self.auth_token
        self.ensure_data_dir()
        token_file = self.data_dir / "auth_token"
        if token_file.exists():
            token = token_file.read_text(encoding="utf-8").strip()
            if token:
                self.auth_token = token
                return token
        token = secrets.token_urlsafe(32)
        token_file.write_text(token, encoding="utf-8")
        try:  # best effort：Windows 下 chmod 语义有限，失败不影响功能
            token_file.chmod(0o600)
        except OSError:  # pragma: no cover - platform dependent
            pass
        self.auth_token = token
        return token


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内单例。测试通过 ``get_settings.cache_clear()`` 重置。"""
    settings = Settings()
    # 生产环境禁止 CORS 通配符
    if settings.env == "production" and "*" in settings.cors_origins:
        raise ValueError("wildcard CORS origin is not allowed in production")
    settings.ensure_data_dir()
    return settings
