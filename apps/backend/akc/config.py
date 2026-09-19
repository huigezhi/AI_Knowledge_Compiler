"""集中配置。

规则：
* 所有配置来自环境变量（可选 .env 文件），**启动时集中校验、快速失败**；
* 密钥只存在于环境变量 / 本地文件中，绝不写入代码库；
* 模型 ID 一律配置注入，业务代码不得硬编码模型名。

变量前缀统一为 ``AKC_``，与仓库根目录 ``.env.example`` 一一对应。
"""

from __future__ import annotations

import os
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

# LLM 端点预设：编译只需「Anthropic Messages 兼容」的接口即可，
# 因此除了官方 Anthropic，也能直接接 DeepSeek 的 Anthropic 兼容端点。
# 注意这里只预设**地址**，不预设模型名 —— 模型 ID 一律由配置注入。
LLM_BASE_URL_PRESETS: dict[str, str] = {
    "anthropic": "https://api.anthropic.com",
    "deepseek": "https://api.deepseek.com/anthropic",
    # custom 没有预设：不填 AKC_LLM_BASE_URL 就报错，避免静默打到 Anthropic
    "custom": "",
}

# 允许用环境变量指定配置文件；空字符串表示**不读 .env 文件**（测试/CI 用）。
_ENV_FILE = os.environ.get("AKC_ENV_FILE", ".env").strip()


class Settings(BaseSettings):
    """运行环境配置。"""

    model_config = SettingsConfigDict(
        env_prefix="AKC_",
        # 默认读工作目录下的 .env；可用 AKC_ENV_FILE 覆盖（设为空字符串即**不读任何 .env 文件**，
        # 测试与 CI 靠它避免被开发者本机的真实配置污染）。
        env_file=(_ENV_FILE or None),
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

    # --- LLM / compiler（provider 中立；支持 Anthropic 或任何 Anthropic 兼容端点）---
    llm_enabled: bool = False
    # anthropic | deepseek | custom —— 决定 base_url 预设，见 LLM_BASE_URL_PRESETS
    llm_provider: str = "anthropic"
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None  # 未设置时按 provider 预设
    llm_max_context_tokens: int = 50_000
    llm_timeout_seconds: float = 120.0

    # --- 兼容旧配置名（AKC_CLAUDE_*，等价于上面的 AKC_LLM_*）-----------------
    claude_enabled: bool = False
    claude_model: str | None = None
    claude_api_key: str | None = None
    claude_base_url: str | None = None
    claude_max_context_tokens: int | None = None
    claude_timeout_seconds: float | None = None

    # --- compile policy ----------------------------------------------------
    auto_compile: bool = False
    # 编译成功后自动把产出的知识写入 Obsidian vault（无需扩展再调 /obsidian/sync）。
    # 这是"全程无人工干预"链路的最后一环：采集 -> 入库 -> 编译 -> 落盘。
    auto_write_obsidian: bool = False
    auto_merge_verified: bool = False
    require_review_for_conflicts: bool = True

    # --- job queue ---------------------------------------------------------
    job_poll_interval_seconds: float = 2.0
    job_max_attempts: int = 3
    job_backoff_seconds: Annotated[list[int], NoDecode] = Field(default_factory=lambda: [2, 5, 15])

    # ------------------------------------------------------------------ 校验
    @field_validator(
        "vault_path",
        "llm_model",
        "llm_api_key",
        "llm_base_url",
        "claude_model",
        "claude_api_key",
        "claude_base_url",
        "auth_token",
        mode="before",
    )
    @classmethod
    def _empty_string_is_unset(cls, value: object) -> object:
        """空值等同「未配置」。

        关键：`.env` 里写 `AKC_VAULT_PATH=`（空值）时，pydantic 会把空串解析成
        ``Path('.')`` —— 这是**真值**，会让「未配置 Vault」的校验被绕过，
        同步时把文件写进当前工作目录。这里统一把空串归一为 None。
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("llm_provider", mode="before")
    @classmethod
    def _check_llm_provider(cls, v: object) -> object:
        """校验 provider，避免拼错后静默回落到 Anthropic 默认地址。

        没有这层校验时，`AKC_LLM_PROVIDER=DeepSeek`（大小写）或 `deep-seek`
        都会查不到预设，悄悄用默认 endpoint —— 表现为「配了 DeepSeek 却一直 401」，
        排查成本很高。这里直接报错并列出可用值。
        """
        if not isinstance(v, str) or not v.strip():
            return "anthropic"
        name = v.strip().lower()
        if name not in LLM_BASE_URL_PRESETS:
            known = "、".join(sorted(LLM_BASE_URL_PRESETS))
            raise ValueError(
                f"AKC_LLM_PROVIDER={v!r} 不是已知 provider，可用值：{known}。"
                "若要接自建/兼容端点，请用 custom 并显式设置 AKC_LLM_BASE_URL。"
            )
        return name

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
    def _merge_llm_aliases(self) -> Settings:
        """把旧配置名（AKC_CLAUDE_*）并入新的 provider 中立配置（AKC_LLM_*）。

        规则：AKC_LLM_* 优先；未设置的项回落到 AKC_CLAUDE_*，最后回落到 provider 预设。
        合并后**同时写回两组字段**，这样旧代码/旧配置继续可用，不会因为改名而失效。
        """
        if self.claude_enabled:
            self.llm_enabled = True
        self.claude_enabled = self.llm_enabled

        if self.llm_model is None:
            self.llm_model = self.claude_model
        self.claude_model = self.llm_model

        if self.llm_api_key is None:
            self.llm_api_key = self.claude_api_key
        self.claude_api_key = self.llm_api_key

        if self.llm_base_url is None:
            self.llm_base_url = self.claude_base_url
        if self.llm_base_url is None:
            self.llm_base_url = LLM_BASE_URL_PRESETS.get(self.llm_provider, "")
        if not self.llm_base_url:
            # custom 没有预设地址：启用编译时必须显式给出，否则不知道该往哪发。
            if self.llm_enabled:
                raise ValueError(
                    "AKC_LLM_PROVIDER=custom 时必须显式设置 AKC_LLM_BASE_URL"
                    "（例如 http://localhost:11434）。"
                )
            self.llm_base_url = LLM_BASE_URL_PRESETS["anthropic"]
        self.llm_base_url = self.llm_base_url.rstrip("/")
        self.claude_base_url = self.llm_base_url

        if self.claude_max_context_tokens:
            self.llm_max_context_tokens = self.claude_max_context_tokens
        self.claude_max_context_tokens = self.llm_max_context_tokens

        if self.claude_timeout_seconds:
            self.llm_timeout_seconds = self.claude_timeout_seconds
        self.claude_timeout_seconds = self.llm_timeout_seconds
        return self

    @model_validator(mode="after")
    def _check_compiler(self) -> Settings:
        if self.llm_enabled and not (self.llm_api_key and self.llm_model):
            raise ValueError(
                "启用编译需要同时配置 API Key 与模型 ID："
                "AKC_LLM_API_KEY + AKC_LLM_MODEL"
                "（兼容旧名 AKC_CLAUDE_API_KEY / AKC_CLAUDE_MODEL）；"
                "模型 ID 不硬编码在代码里，示例见 .env.example"
            )
        if self.llm_max_context_tokens < 1_000:
            raise ValueError("AKC_LLM_MAX_CONTEXT_TOKENS must be >= 1000")
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
